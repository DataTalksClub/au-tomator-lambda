"""Record Slack delete actions for later review.

Each delete action (single-message delete, thread wipe, broadcast removal,
or ban-user cleanup) is stored three ways:

1. A structured CloudWatch log line (`DELETE_AUDIT ...`) — already paying
   for the Lambda log group; useful for the last couple of weeks.
2. DynamoDB (`automator-delete-audit`) with a TTL — query by target user or
   by date while the item is hot.
3. S3 (`dtc-automator-delete-audit-<account>`) — the cheap forever copy.
   Dual-written at event time so there is no extra dump Lambda.

DynamoDB is PAY_PER_REQUEST and S3 Standard. Glacier / Standard-IA would
cost more here: they round each object up to 128 KB, and these records are
a few KB. Leave the objects in Standard.

Writes never raise to the caller. A failed audit must not block a delete.
"""

import json
import os
import time
from datetime import datetime, timezone

from logs import logger


AUDIT_TABLE = os.getenv('AUDIT_TABLE', 'automator-delete-audit')
AUDIT_BUCKET = os.getenv(
    'AUDIT_BUCKET', 'dtc-automator-delete-audit-387546586013'
)
AUDIT_TTL_DAYS = int(os.getenv('AUDIT_TTL_DAYS', '90'))
TEXT_LIMIT = 4000


def _utcnow():
    return datetime.now(timezone.utc)


def _clip(text):
    text = text or ''
    if len(text) <= TEXT_LIMIT:
        return text
    return text[:TEXT_LIMIT] + '…'


def _drop_none(value):
    if isinstance(value, dict):
        return {k: _drop_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_drop_none(v) for v in value]
    return value


def _action_id(event):
    item = event.get('item') or {}
    parts = [
        item.get('channel') or 'no-channel',
        item.get('ts') or 'no-ts',
        event.get('reaction') or 'no-reaction',
        event.get('event_ts') or event.get('ts') or 'no-event-ts',
    ]
    return ':'.join(str(p) for p in parts)


def build_audit_record(
    event,
    action_type,
    deleted_messages,
    *,
    target_user_id=None,
    target_user=None,
    channel_name=None,
    extra=None,
    fake_delete=False,
    now=None,
):
    """Build the audit document (no I/O)."""
    now = now or _utcnow()
    item = event.get('item') or {}
    recorded_at = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    day = now.strftime('%Y-%m-%d')
    action_id = _action_id(event)

    messages = []
    for msg in deleted_messages or []:
        messages.append({
            'channel': msg.get('channel'),
            'ts': msg.get('ts'),
            'user': msg.get('user'),
            'text': _clip(msg.get('text')),
            'kind': msg.get('kind') or 'parent',
            'ok': bool(msg.get('ok', True)),
            'fake': bool(msg.get('fake', fake_delete)),
        })

    target = target_user_id or (target_user or {}).get('id')
    record = {
        'action_id': action_id,
        'recorded_at': recorded_at,
        'action_type': action_type,
        'reaction': event.get('reaction'),
        'triggered_by': event.get('user'),
        'event_ts': event.get('event_ts') or event.get('ts'),
        'channel': item.get('channel'),
        'channel_name': channel_name,
        'message_ts': item.get('ts'),
        'item_user': event.get('item_user'),
        'target_user_id': target,
        'target_user': target_user,
        'fake_delete': bool(fake_delete),
        'deleted_count': len(messages),
        'deleted_ok_count': sum(1 for m in messages if m['ok']),
        'deleted_messages': messages,
        'extra': extra or {},
        'pk': f"USER#{target or 'unknown'}",
        'sk': f"{recorded_at}#{action_id}",
        'gsi1pk': f"DATE#{day}",
        'gsi1sk': f"{recorded_at}#{action_id}",
        'expires_at': int(now.timestamp()) + AUDIT_TTL_DAYS * 86400,
    }
    return _drop_none(record)


def s3_keys(record):
    recorded_at = record['recorded_at']
    year, month, day = recorded_at[:10].split('-')
    action_id = record['action_id'].replace('/', '_')
    keys = [f"by-date/{year}/{month}/{day}/{action_id}.json"]
    user_id = record.get('target_user_id')
    if user_id:
        keys.append(
            f"by-user/{user_id}/{year}/{month}/{day}/{action_id}.json"
        )
    return keys


def _put_dynamo(item):
    import boto3

    table = boto3.resource('dynamodb').Table(AUDIT_TABLE)
    table.put_item(Item=item)


def _put_s3(key, body):
    import boto3

    boto3.client('s3').put_object(
        Bucket=AUDIT_BUCKET,
        Key=key,
        Body=body.encode('utf-8'),
        ContentType='application/json',
    )


def _aws_enabled():
    return os.getenv('AUDIT_ENABLED', '1') == '1'


def record_delete_action(
    event,
    action_type,
    deleted_messages,
    *,
    target_user_id=None,
    target_user=None,
    channel_name=None,
    extra=None,
    fake_delete=False,
):
    """Log the action and persist it to DynamoDB + S3. Never raises."""
    try:
        record = build_audit_record(
            event,
            action_type,
            deleted_messages,
            target_user_id=target_user_id,
            target_user=target_user,
            channel_name=channel_name,
            extra=extra,
            fake_delete=fake_delete,
        )
    except Exception as exc:
        logger.info(f"DELETE_AUDIT build failed: {exc}")
        return None

    logger.info('DELETE_AUDIT ' + json.dumps(record, default=str))

    if not _aws_enabled():
        return record

    try:
        _put_dynamo(record)
    except Exception as exc:
        logger.info(f"DELETE_AUDIT dynamodb write failed: {exc}")

    body = json.dumps(record, default=str, indent=2)
    for key in s3_keys(record):
        try:
            _put_s3(key, body)
        except Exception as exc:
            logger.info(f"DELETE_AUDIT s3 write failed key={key}: {exc}")

    return record
