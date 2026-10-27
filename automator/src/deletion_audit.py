"""Fail-closed client for the moderation app's v1 deletion audit API."""
import json
import os
from urllib.parse import urlsplit

import requests

from logs import logger


def configuration():
    url = os.environ.get('MOD_API_URL', '').rstrip('/')
    token = os.environ.get('MOD_API_TOKEN', '').strip()
    parsed = urlsplit(url)
    if (os.environ.get('MOD_AUDIT_ENABLED') != 'true' or not token
            or parsed.scheme != 'https' or parsed.netloc != 'mod.dtcdev.click'
            or parsed.path or parsed.query or parsed.fragment):
        raise RuntimeError('Moderation audit must be enabled with its HTTPS URL and token')
    return url, token


def _post(path, payload, committed=False):
    url, token = configuration()
    response = requests.post(
        url + path, json=payload,
        headers={'Authorization': f'Bearer {token}'},
        timeout=(3, 10), allow_redirects=False,
    )
    if response.status_code not in (200, 201):
        raise RuntimeError('Moderation audit API did not acknowledge write')
    if committed:
        result = response.json()
        if (not isinstance(result, dict) or result.get('committed') is not True
                or result.get('channel') != payload['channel']
                or result.get('ts') != payload['ts']):
            raise RuntimeError('Moderation audit API did not confirm matching commit')


def persist(record, alert):
    payload = {key: record[key] for key in (
        'text', 'files', 'user', 'channel', 'ts', 'thread_ts',
        'reacting_admin', 'reaction',
    )}
    payload.update({
        'channel_name': record.get('channel_name', ''),
        'source': 'au-tomator',
        'reason': 'moderator reaction',
        'deleted_at': record['timestamp'],
    })
    for attempt in (1, 2):
        try:
            _post('/api/v1/deleted-messages', payload, committed=True)
            return payload
        except (requests.RequestException, RuntimeError, ValueError):
            # Never include response bodies, request headers, or exceptions:
            # they can contain credentials or private message content.
            alert('AUDIT_WRITE_FAILED', record['channel'], record['ts'], attempt)
    raise RuntimeError('Deletion skipped: moderation audit write failed twice')


def receipt(payload, alert):
    receipt = {key: payload[key] for key in ('channel', 'ts', 'source', 'deleted_at')}
    # CloudWatch is the durable receipt journal; replay by channel/ts is safe.
    logger.info(json.dumps({'tag': 'AUDIT_DELETE_RECEIPT', **receipt}))
    for attempt in (1, 2):
        try:
            _post('/api/v1/delete-receipts', receipt)
            logger.info(json.dumps({'tag': 'AUDIT_DELETE_RECEIPT_SENT', **receipt}))
            return
        except (requests.RequestException, RuntimeError, ValueError):
            alert('AUDIT_RECEIPT_PENDING', payload['channel'], payload['ts'], attempt)
