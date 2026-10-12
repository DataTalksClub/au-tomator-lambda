"""Cross-channel similar-message tracker.

Each qualifying post updates a DynamoDB aggregate per (user, fingerprint):
channel set, message list, last_seen. Sessions that have reached two
channels sit on a sparse GSI (`ready` / last_seen). EventBridge every 5
minutes flushes aggregates whose last_seen is older than quiet_seconds.
"""

import hashlib
import os
import re
import time
from difflib import SequenceMatcher

from logs import logger


SPAM_TABLE = os.getenv('SPAM_TABLE', 'automator-spam-sessions')
TTL_SECONDS = 24 * 3600
MAX_TRACKED_MESSAGES = 200
READY_PK = 'ready'

_SKIP_SUBTYPES = {
    'bot_message',
    'message_changed',
    'message_deleted',
    'channel_join',
    'channel_leave',
    'channel_topic',
    'channel_purpose',
    'message_replied',
}


def tracker_config(config):
    return (config or {}).get('spam_tracker') or {}


def enabled(config):
    if os.getenv('SPAM_TRACKER_ENABLED', '1') != '1':
        return False
    cfg = tracker_config(config)
    return cfg.get('enabled', True)


def quiet_seconds(config):
    seconds = int(tracker_config(config).get('quiet_seconds', 180))
    return max(30, min(seconds, 3600))


def min_channels(config):
    return int(tracker_config(config).get('min_channels', 2))


def min_chars(config):
    return int(tracker_config(config).get('min_chars', 40))


def similarity_threshold(config):
    return float(tracker_config(config).get('similarity', 0.88))


def normalize_text(text):
    text = text or ''
    text = re.sub(r'<(https?://[^|>]+)(?:\|[^>]*)?>', r'\1', text)
    text = re.sub(r'<#[A-Z0-9]+\|([^>]+)>', r'#\1', text)
    text = re.sub(r'<@[A-Z0-9]+>', ' ', text)
    text = text.lower()
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def fingerprint(text):
    normalized = normalize_text(text)
    digest = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    return digest[:16]


def is_similar(left, right, threshold=0.88):
    a = normalize_text(left)
    b = normalize_text(right)
    if not a or not b:
        return False
    if a == b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= threshold


def should_ingest(event, config):
    if not enabled(config):
        return False
    if (event or {}).get('type') != 'message':
        return False
    if event.get('bot_id') or event.get('subtype') in _SKIP_SUBTYPES:
        return False
    user = event.get('user')
    if not user:
        return False
    if user in set((config or {}).get('admins') or []):
        return False
    text = event.get('text') or ''
    if len(normalize_text(text)) < min_chars(config):
        return False
    if not event.get('channel') or not event.get('ts'):
        return False
    return True


def session_key(user_id, fp):
    return {'pk': f'USER#{user_id}', 'sk': f'FP#{fp}'}


def _message_entry(event):
    return {
        'channel': event.get('channel'),
        'ts': event.get('ts'),
        'text': event.get('text') or '',
        'thread_ts': event.get('thread_ts'),
    }


def unique_channels(messages):
    return {m.get('channel') for m in messages if m.get('channel')}


def mark_ready(item, channel_count, now, threshold):
    """Sparse GSI: only multi-channel sessions are scanable."""
    item['channel_count'] = channel_count
    item['last_seen'] = int(now)
    if channel_count >= threshold:
        item['gsi1pk'] = READY_PK
        item['gsi1sk'] = int(now)
    else:
        item.pop('gsi1pk', None)
        item.pop('gsi1sk', None)
    return item


def _table():
    import boto3
    return boto3.resource('dynamodb').Table(SPAM_TABLE)


def load_sessions(user_id):
    from boto3.dynamodb.conditions import Key

    table = _table()
    items = []
    kwargs = {
        'KeyConditionExpression': Key('pk').eq(f'USER#{user_id}'),
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get('Items') or [])
        if 'LastEvaluatedKey' not in resp:
            break
        kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
    return items


def load_session(user_id, fp):
    table = _table()
    resp = table.get_item(Key=session_key(user_id, fp))
    return resp.get('Item')


def save_session(item):
    _table().put_item(Item=item)


def delete_session(user_id, fp):
    _table().delete_item(Key=session_key(user_id, fp))


def list_ready_sessions(cutoff):
    """Sessions on the ready GSI whose last_seen is at or before cutoff."""
    from boto3.dynamodb.conditions import Key

    table = _table()
    items = []
    kwargs = {
        'IndexName': 'gsi1',
        'KeyConditionExpression': (
            Key('gsi1pk').eq(READY_PK) & Key('gsi1sk').lte(int(cutoff))
        ),
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get('Items') or [])
        if 'LastEvaluatedKey' not in resp:
            break
        kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
    return items


def find_matching_session(sessions, text, threshold):
    for item in sessions:
        canonical = item.get('canonical_text') or ''
        if is_similar(text, canonical, threshold):
            return item
    return None


def ingest_message(event, config, *, now=None, store=None):
    """Fold a message into the (user, fingerprint) aggregate. No I/O besides Dynamo."""
    if not should_ingest(event, config):
        return None

    now = now if now is not None else time.time()
    user_id = event['user']
    text = event.get('text') or ''
    fp = fingerprint(text)
    threshold = similarity_threshold(config)
    hooks = store or {}
    load = hooks.get('load_sessions') or load_sessions
    save = hooks.get('save_session') or save_session

    try:
        sessions = load(user_id)
    except Exception as exc:
        logger.info(f"spam tracker load failed: {exc}")
        return None

    item = find_matching_session(sessions, text, threshold)
    if item is None:
        item = {
            'pk': f'USER#{user_id}',
            'sk': f'FP#{fp}',
            'user_id': user_id,
            'fingerprint': fp,
            'canonical_text': text,
            'messages': [],
            'status': 'collecting',
        }

    messages = list(item.get('messages') or [])
    key = (event.get('channel'), event.get('ts'))
    if not any((m.get('channel'), m.get('ts')) == key for m in messages):
        if len(messages) < MAX_TRACKED_MESSAGES:
            messages.append(_message_entry(event))
    item['messages'] = messages
    item['expires_at'] = int(now) + TTL_SECONDS
    item['status'] = 'collecting'
    mark_ready(item, len(unique_channels(messages)), now, min_channels(config))

    try:
        save(item)
    except Exception as extra:
        logger.info(f"spam tracker save failed: {extra}")
        return item

    if item.get('gsi1pk') == READY_PK:
        logger.info(
            f"spam tracker aggregate user={user_id} fp={item['fingerprint']} "
            f"channels={item.get('channel_count')} last_seen={item.get('last_seen')}"
        )
    return item
