#!/usr/bin/env python3
"""Query recorded Slack delete actions.

Examples:
  python scripts/query_delete_audit.py --user U123
  python scripts/query_delete_audit.py --date 2026-04-08
  python scripts/query_delete_audit.py --user U123 --s3
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import boto3


TABLE = os.getenv('AUDIT_TABLE', 'automator-delete-audit')
BUCKET = os.getenv('AUDIT_BUCKET', 'dtc-automator-delete-audit-387546586013')
REGION = os.getenv('AWS_REGION', 'eu-west-1')


def _print(records):
    print(json.dumps(records, indent=2, default=str))
    print(f'{len(records)} record(s)', file=sys.stderr)


def query_user(user_id):
    dynamodb = boto3.resource('dynamodb', region_name=REGION)
    table = dynamodb.Table(TABLE)
    items = []
    kwargs = {
        'KeyConditionExpression': boto3.dynamodb.conditions.Key('pk').eq(
            f'USER#{user_id}'
        )
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get('Items', []))
        if 'LastEvaluatedKey' not in resp:
            break
        kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
    return items


def query_date(day):
    dynamodb = boto3.resource('dynamodb', region_name=REGION)
    table = dynamodb.Table(TABLE)
    items = []
    kwargs = {
        'IndexName': 'gsi1',
        'KeyConditionExpression': boto3.dynamodb.conditions.Key('gsi1pk').eq(
            f'DATE#{day}'
        ),
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get('Items', []))
        if 'LastEvaluatedKey' not in resp:
            break
        kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
    return items


def list_s3(user_id=None, day=None):
    s3 = boto3.client('s3', region_name=REGION)
    if user_id:
        prefix = f'by-user/{user_id}/'
        if day:
            year, month, rest = day.split('-', 2)
            prefix = f'by-user/{user_id}/{year}/{month}/{rest}/'
    elif day:
        year, month, rest = day.split('-', 2)
        prefix = f'by-date/{year}/{month}/{rest}/'
    else:
        raise SystemExit('--s3 requires --user and/or --date')

    records = []
    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get('Contents') or []:
            body = s3.get_object(Bucket=BUCKET, Key=obj['Key'])['Body'].read()
            records.append(json.loads(body))
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user', help='Slack user id the action targeted')
    parser.add_argument('--date', help='UTC calendar day YYYY-MM-DD')
    parser.add_argument(
        '--s3', action='store_true',
        help='Read the forever S3 copy instead of DynamoDB',
    )
    args = parser.parse_args()

    if args.s3:
        _print(list_s3(user_id=args.user, day=args.date))
        return
    if args.user:
        _print(query_user(args.user))
        return
    if args.date:
        _print(query_date(args.date))
        return
    parser.error('pass --user, --date, or --s3 with one of those')


if __name__ == '__main__':
    main()
