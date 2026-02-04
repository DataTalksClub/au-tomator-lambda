import os
import re
import requests


from logs import logger

SLACK_TOKEN = os.getenv('SLACK_TOKEN')
USER_SLACK_TOKEN = os.getenv('USER_SLACK_TOKEN')


def post_message_thread(event, message):
    item = event['item']
    channel = item['channel']
    thread_ts = item['ts']

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


def get_message_content(channel, ts):
    params = {
        'channel': channel,
        'ts': ts
    }

    headers = {
        'Authorization': f'Bearer {SLACK_TOKEN}'
    }

    url = 'https://slack.com/api/conversations.replies'
    response = requests.get(url, params=params, headers=headers)
    response.raise_for_status()

    response_json = response.json()
    all_messages = response_json.get('messages', [])
    if not all_messages:
        return None
    message = find_message_by_ts(all_messages, ts)
    return message


def get_thread_replies(channel, ts):
    """Get all replies in a thread (excluding the parent message)"""
    params = {
        'channel': channel,
        'ts': ts
    }

    headers = {
        'Authorization': f'Bearer {SLACK_TOKEN}'
    }

    url = 'https://slack.com/api/conversations.replies'
    response = requests.get(url, params=params, headers=headers)
    response.raise_for_status()

    response_json = response.json()
    all_messages = response_json.get('messages', [])
    
    # Filter out the parent message (first message with ts == thread_ts)
    thread_replies = [msg for msg in all_messages if msg['ts'] != ts]
    
    return thread_replies


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


def remove_message(channel, ts):
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
    return response.json()


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
