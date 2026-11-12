"""Opt-in live proof: ask through Slack as a user and inspect the real bot reply.

Runs inside the normal deployment role; secrets remain in process memory.
Only the labelled test thread and its public CMP answer are printed.
"""
import json
import os
import time

import boto3
import requests


CHANNEL = 'C0288NJ5XSA'
QUESTION = 'Have the peer review items for Project 1 been assigned?'


def slack_call(token, method, **payload):
    response = requests.post(
        f'https://slack.com/api/{method}', json=payload,
        headers={'Authorization': f'Bearer {token}'}, timeout=(3, 10),
    )
    response.raise_for_status()
    data = response.json()
    if not data.get('ok'):
        raise RuntimeError(f'Slack {method} failed: {data.get("error")}')
    return data


def main():
    client = boto3.client('lambda', region_name=os.environ.get('AWS_REGION', 'eu-west-1'))
    environment = client.get_function_configuration(
        FunctionName='automator-process-reaction')['Environment']['Variables']
    if environment.get('CMP_CONTEXT_ENABLED') != '1':
        raise RuntimeError('CMP integration is not enabled')
    snapshot = requests.get(
        'https://courses.datatalks.club/api/bot/courses/ml-zoomcamp-2026/state/',
        headers={'Authorization': f'Bearer {environment["CMP_BOT_READ_TOKEN"]}'},
        timeout=(3, 10), allow_redirects=False,
    )
    snapshot.raise_for_status()
    public = snapshot.json()
    print(json.dumps({'observed_cmp_projects': [
        {key: project[key] for key in ('title', 'state', 'peer_review_open',
                                     'assignments_created', 'peer_review_due_date')}
        for project in public['projects']
    ]}, ensure_ascii=False), flush=True)
    bot_token, user_token = environment['SLACK_TOKEN'], environment['USER_SLACK_TOKEN']
    bot = slack_call(bot_token, 'auth.test')
    user = slack_call(user_token, 'auth.test')
    if user.get('bot_id') or user['team_id'] != environment['CMP_SLACK_TEAM_ID']:
        raise RuntimeError('Proof requires an authenticated workspace user')
    root = slack_call(
        user_token, 'chat.postMessage', channel=CHANNEL,
        text=f'[CMP integration test] <@{bot["user_id"]}> {QUESTION}',
        unfurl_links=False, unfurl_media=False,
    )
    ts = root['ts']
    print(f'Live question: {QUESTION}', flush=True)
    print(f'Thread: https://datatalks-club.slack.com/archives/{CHANNEL}/p{ts.replace(".", "")}', flush=True)
    # Polling is bounded and does not invoke Lambda directly: this exercises
    # Slack event delivery, router, automator, CMP, FAQ model and Slack reply.
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        replies = slack_call(bot_token, 'conversations.replies', channel=CHANNEL, ts=ts)['messages']
        for message in replies:
            if message.get('ts') == ts or message.get('user') != bot['user_id']:
                continue
            text = message.get('text', '')
            for block in message.get('blocks', []):
                text += '\n' + (block.get('text') or {}).get('text', '')
            if 'courses.datatalks.club/' not in text or 'peer review' not in text.lower().replace('-', ' '):
                raise RuntimeError('Bot reply lacks factual CMP citation/peer review answer')
            if any(phrase in text.lower() for phrase in (
                "can't confirm", 'cannot confirm', "couldn't find a current value",
                "can't verify", 'cannot verify',
            )):
                raise RuntimeError('Bot returned generic uncertainty despite live CMP state')
            if 'assigned_count' in text or 'pending_count' in text:
                raise RuntimeError('Private field leaked into public reply')
            print(json.dumps({'answer': text, 'reply_ts': message['ts']}, ensure_ascii=False), flush=True)
            return
        time.sleep(5)
    raise RuntimeError('No bot answer within 150 seconds')


if __name__ == '__main__':
    main()
