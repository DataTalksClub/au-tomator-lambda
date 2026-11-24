import os
import re
import requests
import json
from contextvars import ContextVar
from datetime import datetime, timezone
import deletion_audit


from logs import logger

SLACK_TOKEN = os.getenv('SLACK_TOKEN')
USER_SLACK_TOKEN = os.getenv('USER_SLACK_TOKEN')
deletion_context = ContextVar('deletion_context', default=None)


def _private_post(method, payload):
    # These messages may contain student counts: no message/body logging.
    response = requests.post(
        f'https://slack.com/api/{method}', json=payload,
        headers={'Authorization': f'Bearer {SLACK_TOKEN}'}, timeout=(2, 5),
    )
    response.raise_for_status()
    if response.json().get('ok') is not True:
        raise RuntimeError('Private Slack delivery failed')


def post_private_message(user, message):
    _private_post('chat.postMessage', {'channel': user, 'text': message})


def post_ephemeral(channel, user, thread_ts, message):
    _private_post('chat.postEphemeral', {
        'channel': channel, 'user': user, 'thread_ts': thread_ts, 'text': message,
    })


def alert_deletion_audit(tag, channel, ts, attempt=0):
    logger.error(json.dumps({
        'tag': tag, 'channel': channel, 'ts': ts, 'attempt': attempt,
    }))
    context = deletion_context.get() or {}
    recipients = set(context.get('audit_admins') or [])
    if context.get('user'):
        recipients.add(context['user'])
    for admin in recipients:
        try:
            result = send_dm(admin, f'{tag}: channel={channel} ts={ts} attempt={attempt}')
            if not result.get('ok'):
                logger.error('AUDIT_ALERT_DELIVERY_FAILED')
        except Exception:
            logger.error('AUDIT_ALERT_DELIVERY_FAILED')


def post_message_thread(event, message):
    item = event['item']
    channel = item['channel']
    thread_ts = item['ts']

    return post_message_to_thread(channel, thread_ts, message)


def post_message_to_thread(channel, thread_ts, message):
    url = 'https://slack.com/api/chat.postMessage'

    message_request = {
        "channel": channel,
        "thread_ts": thread_ts,
        "blocks": [{
            "type": "section",
            "text": {"type": "mrkdwn", "text": message}
        }]
    }

    headers = {
        'Authorization': f'Bearer {SLACK_TOKEN}'
    }

    logger.info(f'posting {message} to {channel}...')
    response = requests.post(url, json=message_request, headers=headers)
    response.raise_for_status()

    response_json = response.json()
    return response_json


def find_message_by_ts(messages, ts):
    for msg in messages:
        if msg['ts'] == ts:
            return msg
    return None


_CONVERSATIONS_FALLBACK_ERRORS = {
    'not_in_channel',
    'channel_not_found',
    'missing_scope',
    'not_allowed_token_type',
}


def _candidate_tokens():
    tokens = [SLACK_TOKEN]
    if USER_SLACK_TOKEN and USER_SLACK_TOKEN != SLACK_TOKEN:
        tokens.append(USER_SLACK_TOKEN)
    return tokens


def _conversations_get(method, params):
    url = f'https://slack.com/api/{method}'
    tokens = _candidate_tokens()
    last_json = {}
    for idx, token in enumerate(tokens):
        headers = {'Authorization': f'Bearer {token}'}
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        response_json = response.json()
        last_json = response_json
        if response_json.get('ok', True):
            return response_json
        error = response_json.get('error')
        if error not in _CONVERSATIONS_FALLBACK_ERRORS or idx == len(tokens) - 1:
            logger.info(f"{method} failed for {params}: {error}")
            return response_json
    return last_json


def get_message_content(channel, ts, thread_ts=None):
    if thread_ts and thread_ts != ts:
        thread_json = _conversations_get(
            'conversations.replies', {'channel': channel, 'ts': thread_ts}
        )
        message = find_message_by_ts(thread_json.get('messages', []), ts)
        if message:
            return message

    response_json = _conversations_get(
        'conversations.replies', {'channel': channel, 'ts': ts}
    )
    message = find_message_by_ts(response_json.get('messages', []), ts)
    if message:
        return message

    # Fallback for top-level messages when conversations.replies fails or misses.
    history_json = _conversations_get(
        'conversations.history',
        {'channel': channel, 'latest': ts, 'inclusive': True, 'limit': 1},
    )
    return find_message_by_ts(history_json.get('messages', []), ts)


def get_thread_replies(channel, ts, include_parent=False):
    """Get all replies in a thread (optionally including the parent message)"""
    response_json = _conversations_get(
        'conversations.replies', {'channel': channel, 'ts': ts}
    )
    if not response_json.get('ok', True):
        return []

    all_messages = response_json.get('messages', [])
    if include_parent:
        return all_messages

    # Filter out the parent message (first message with ts == thread_ts)
    return [msg for msg in all_messages if msg['ts'] != ts]


def get_thread_messages(channel, ts):
    """Get all messages in a thread (parent message and replies) via conversations.replies"""
    return get_thread_replies(channel, ts, include_parent=True)


def send_dm(user, message):
    url = 'https://slack.com/api/chat.postMessage'

    message_request = {
        "channel": user,
        "blocks": [{
            "type": "section",
            "text": {"type": "mrkdwn", "text": message}
        }]
    }

    headers = {
        'Authorization': f'Bearer {SLACK_TOKEN}'
    }
    
    logger.info(f'posting {message} to {user}...')
    response = requests.post(url, json=message_request, headers=headers)
    response.raise_for_status()
    return response.json()


def send_dm_blocks(user, message, blocks):
    url = 'https://slack.com/api/chat.postMessage'

    message_request = {
        "channel": user,
        "text": message,
        "blocks": blocks,
    }

    headers = {
        'Authorization': f'Bearer {SLACK_TOKEN}'
    }

    logger.info(f'posting blocks DM to {user}...')
    response = requests.post(url, json=message_request, headers=headers)
    response.raise_for_status()
    return response.json()


def remove_message(channel, ts, thread_ts=None):
    # Keep the guard at the sole chat.delete boundary so every deletion path,
    # including ban sweeps and thread replies, must first preserve the message.
    try:
        if thread_ts and thread_ts != ts:
            message = get_message_content(channel, ts, thread_ts=thread_ts)
        else:
            message = get_message_content(channel, ts)
    except Exception:
        alert_deletion_audit('AUDIT_DELETED_MESSAGE_FAILED', channel, ts)
        raise RuntimeError('Deletion skipped: full message fetch failed') from None
    if not isinstance(message, dict) or message.get('ts') != ts:
        alert_deletion_audit('AUDIT_DELETED_MESSAGE_FAILED', channel, ts)
        raise RuntimeError('Deletion skipped: full message unavailable for audit')
    context = deletion_context.get() or {}
    record = {
        'tag': 'AUDIT_DELETED_MESSAGE',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'channel': channel,
        'channel_name': (context.get('audit_channels') or {}).get(channel, ''),
        'ts': ts,
        'thread_ts': message.get('thread_ts'),
        'user': message.get('user') or message.get('bot_id') or '',
        'text': message.get('text', ''),
        'files': message.get('files', []),
        'reacting_admin': context.get('user'),
        'reaction': context.get('reaction'),
        'message': message,
    }
    # Serialization/logging errors deliberately prevent chat.delete.
    try:
        logger.info(json.dumps(record, ensure_ascii=True))
    except Exception:
        alert_deletion_audit('AUDIT_DELETED_MESSAGE_FAILED', channel, ts)
        raise RuntimeError('Deletion skipped: audit log failed') from None
    payload = deletion_audit.persist(record, alert_deletion_audit)
    url = 'https://slack.com/api/chat.delete'

    message_request = {
        "channel": channel,
        "ts": ts
    }

    headers = {
        'Authorization': f'Bearer {USER_SLACK_TOKEN}'
    }

    logger.info(f'removing message from {channel} at {ts}...')
    response = requests.post(url, json=message_request, headers=headers)
    response.raise_for_status()
    result = response.json()
    if result.get('ok'):
        deletion_audit.receipt(payload, alert_deletion_audit)
    return result


def get_user_info(user_id):
    """Fetch profile info for a Slack user."""
    url = 'https://slack.com/api/users.info'

    params = {'user': user_id}
    headers = {'Authorization': f'Bearer {SLACK_TOKEN}'}

    response = requests.get(url, params=params, headers=headers)
    response.raise_for_status()
    response_json = response.json()

    if not response_json.get('ok'):
        logger.info(f"users.info failed for {user_id}: {response_json.get('error')}")
        return None

    return response_json.get('user')


def _run_search_messages(query):
    url = 'https://slack.com/api/search.messages'
    headers = {'Authorization': f'Bearer {USER_SLACK_TOKEN}'}

    matches = []
    page = 1
    while True:
        params = {'query': query, 'count': 100, 'page': page, 'sort': 'timestamp'}
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        response_json = response.json()

        if not response_json.get('ok'):
            logger.info(f"search.messages failed: {response_json.get('error')}")
            break

        page_info = response_json.get('messages', {})
        matches.extend(page_info.get('matches', []))

        paging = page_info.get('paging', {})
        if page >= paging.get('pages', 1):
            break
        page += 1

    return matches


def search_user_messages(username, after_date, user_id=None):
    """Find messages from a given Slack user posted on or after `after_date` (YYYY-MM-DD).

    Uses search.messages, which requires a user token with search:read.
    Returns a list of message dicts with at least channel/ts/text/permalink.
    """
    if user_id:
        matches = _run_search_messages(f'from:<@{user_id}> after:{after_date}')
        if matches or not username:
            return matches

    if not username:
        return []

    return _run_search_messages(f'from:@{username} after:{after_date}')


def get_user_and_message(event):
    item = event['item']
    channel = item['channel']
    ts = item['ts']

    message_details = get_message_content(channel, ts)

    user = message_details['user']
    message_text = message_details['text']

    return user, message_text


def get_message(event):
    item = event['item']
    channel = item['channel']
    ts = item['ts']

    message_details = get_message_content(channel, ts)

    user = message_details['user']
    message_text = message_details['text']

    return user, message_text


def github_to_slack_markdown(github_markdown: str) -> str:
    slack_markdown = github_markdown

    # Convert headers
    # slack_markdown = re.sub(r'(^|\n)###### (.*)', r'\1*_\2_*', slack_markdown)
    # slack_markdown = re.sub(r'(^|\n)##### (.*)', r'\1*_\2_*', slack_markdown)
    slack_markdown = re.sub(r'(^|\n)#### (.*)', r'\1*_\2_*', slack_markdown)
    slack_markdown = re.sub(r'(^|\n)### (.*)', r'\1*_\2_*', slack_markdown)
    slack_markdown = re.sub(r'(^|\n)## (.*)', r'\1*_\2_*', slack_markdown)
    slack_markdown = re.sub(r'(^|\n)# (.*)', r'\1*_\2_*', slack_markdown)

    # Convert bold text
    slack_markdown = re.sub(r'\*\*(.*?)\*\*', r'*\1*', slack_markdown)
    slack_markdown = re.sub(r'__(.*?)__', r'*\1*', slack_markdown)

    # Convert italic text
    # slack_markdown = re.sub(r'\*(.*?)\*', r'_\1_', slack_markdown)
    # slack_markdown = re.sub(r'_(.*?)_', r'_\1_', slack_markdown)

    # Convert strikethrough text
    # slack_markdown = re.sub(r'~~(.*?)~~', r'~\1~', slack_markdown)

    # Convert links
    slack_markdown = re.sub(r'\[(.*?)\]\((.*?)\)', r'<\2|\1>', slack_markdown)

    # Convert lists
    # slack_markdown = re.sub(r'^\s*[-*]\s+', r'• ', slack_markdown, flags=re.MULTILINE)
    # slack_markdown = re.sub(r'^\s*\d+\.\s+', r'1. ', slack_markdown, flags=re.MULTILINE)

    return slack_markdown
