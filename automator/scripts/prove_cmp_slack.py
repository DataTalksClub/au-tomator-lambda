"""Opt-in live proof: ask through Slack as a user and inspect the real bot reply.

Runs inside the normal deployment role; secrets remain in process memory.
Only the labelled test thread and its public CMP answer are printed.
Exits non-zero when no valid bot reply arrives, and always deletes the
question and the bot's replies afterwards (fails loudly if it cannot).
"""
import json
import os
import time

import boto3
import requests


CHANNEL = 'C0288NJ5XSA'
QUESTION = 'Have the peer review items for Project 1 been assigned?'


def slack_call(token, method, **payload):
    arguments = {'headers': {'Authorization': f'Bearer {token}'}, 'timeout': (3, 10)}
    if method in ('conversations.replies', 'bots.info'):
        response = requests.get(f'https://slack.com/api/{method}', params=payload, **arguments)
    else:
        response = requests.post(f'https://slack.com/api/{method}', json=payload, **arguments)
    response.raise_for_status()
    data = response.json()
    if not data.get('ok'):
        raise RuntimeError(f'Slack {method} failed: {data.get("error")}')
    return data


def ask_as_user(user_token, user_id, bot_id, app_id):
    payload = {
        'channel': CHANNEL, 'as_user': True,
        'text': f'[CMP integration test] <@{bot_id}> {QUESTION}',
        'unfurl_links': False, 'unfurl_media': False,
    }
    result = slack_call(user_token, 'chat.postMessage', **payload)
    message = result.get('message') or {}
    # Slack attaches this app's bot_id to messages posted with its user token;
    # the automator answers those because ``user`` is the human. Any other
    # authorship would be ignored by the bot and make the proof meaningless.
    foreign_app = message.get('bot_id') and message.get('app_id') != app_id
    if message.get('user') != user_id or foreign_app or message.get('subtype') == 'bot_message':
        delete_messages(user_token, [result['ts']])
        raise RuntimeError('Slack did not author the proof question as the authenticated user')
    return result['ts']


def bot_replies(bot_token, ts, bot_user_id):
    messages = slack_call(bot_token, 'conversations.replies', channel=CHANNEL, ts=ts)['messages']
    return [m for m in messages if m.get('ts') != ts and m.get('user') == bot_user_id]


def delete_messages(token, timestamps):
    failures = []
    for ts in timestamps:
        try:
            slack_call(token, 'chat.delete', channel=CHANNEL, ts=ts)
        except Exception as exc:  # report every failure, then fail loudly
            failures.append(f'{ts}: {exc}')
    return failures


def check_answer(message):
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
    return text


def wait_for_answer(bot_token, ts, bot_user_id, timeout=150, interval=5):
    # Polling is bounded and does not invoke Lambda directly: this exercises
    # Slack event delivery, router, automator, CMP, FAQ model and Slack reply.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        replies = bot_replies(bot_token, ts, bot_user_id)
        if replies:
            return replies[0]
        time.sleep(interval)
    raise RuntimeError(f'No bot answer within {timeout} seconds')


def cleanup(bot_token, user_token, ts, bot_user_id):
    """Delete bot replies first, then the question, so no placeholder remains."""
    failures = []
    try:
        replies = [m['ts'] for m in bot_replies(bot_token, ts, bot_user_id)]
    except Exception as exc:
        replies, failures = [], [f'list replies: {exc}']
    failures += delete_messages(bot_token, replies)
    failures += delete_messages(user_token, [ts])
    if failures:
        raise RuntimeError('Proof cleanup failed: ' + '; '.join(failures))
    print(json.dumps({'cleaned_up': {'question_ts': ts, 'reply_ts': replies}}), flush=True)


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
    bot_info = slack_call(bot_token, 'bots.info', bot=bot['bot_id'])
    ts = ask_as_user(user_token, user['user_id'], bot['user_id'], bot_info['bot']['app_id'])
    print(f'Live question: {QUESTION}', flush=True)
    print(f'Thread: https://datatalks-club.slack.com/archives/{CHANNEL}/p{ts.replace(".", "")}', flush=True)
    try:
        reply = wait_for_answer(bot_token, ts, bot['user_id'])
        text = check_answer(reply)
        print(json.dumps({'answer': text, 'reply_ts': reply['ts']}, ensure_ascii=False), flush=True)
        if os.environ.get('PROOF_KEEP_SECONDS'):
            time.sleep(int(os.environ['PROOF_KEEP_SECONDS']))
    finally:
        cleanup(bot_token, user_token, ts, bot['user_id'])


if __name__ == '__main__':
    main()
