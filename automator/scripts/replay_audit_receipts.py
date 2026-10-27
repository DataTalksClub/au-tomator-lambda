"""Replay idempotent durable deletion receipts from filter-log-events JSON."""
import json
import sys

from deletion_audit import _post


def main():
    receipts = {}
    for event in json.load(sys.stdin)['events']:
        record = json.loads(event['message'])
        if record.get('tag') == 'AUDIT_DELETE_RECEIPT':
            payload = {key: record[key] for key in ('channel', 'ts', 'source', 'deleted_at')}
            receipts[(payload['channel'], payload['ts'])] = payload
    for payload in receipts.values():
        _post('/api/v1/delete-receipts', payload)
    print(f'Replayed {len(receipts)} deletion receipts')


if __name__ == '__main__':
    main()
