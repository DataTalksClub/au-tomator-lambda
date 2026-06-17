import os
import re
import time
import json
from datetime import datetime, timedelta

import requests
import yaml

import util
import groqu
import slack
from logs import logger


FAKE_DELETE = os.getenv('FAKE_DELETE', '0') == '1'
CONFIG_FILE = os.getenv('CONFIG_FILE', 'config.yaml')
FAQ_ASSISTANT_URL = os.getenv('FAQ_ASSISTANT_URL', '').strip()
FAQ_ASSISTANT_SHARED_SECRET = os.getenv('FAQ_ASSISTANT_SHARED_SECRET', '')
FAQ_ASSISTANT_TIMEOUT = int(os.getenv('FAQ_ASSISTANT_TIMEOUT', '55'))



with open(CONFIG_FILE, 'r') as f_in:
    config = yaml.safe_load(f_in)


reaction_configs = {}

for c in config['reactions']:
    reaction = c['reaction']
    reaction_configs[reaction] = c


def get_channel_name(channel_id):
    return config['channels'].get(channel_id, None)


def clean_app_mention_text(text):
    text = re.sub(r'<@[A-Z0-9]+>', ' ', text or '')
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def faq_assistant_endpoint():
    if not FAQ_ASSISTANT_URL:
        return None
    if FAQ_ASSISTANT_URL.rstrip('/').endswith('/ask'):
        return FAQ_ASSISTANT_URL
    return f'{FAQ_ASSISTANT_URL.rstrip("/")}/ask'


def course_for_channel(channel_id):
    channel_name = get_channel_name(channel_id)
    course_mapping = (config.get('faq_assistant') or {}).get('courses') or {}
    return course_mapping.get(channel_name)


def build_faq_assistant_payload(event):
    return build_faq_assistant_payload_for_question(
        event.get('channel'),
        event.get('text', ''),
    )


def build_faq_assistant_payload_for_question(channel, question):
    course = course_for_channel(channel)
    payload = {
        'question': clean_app_mention_text(question),
        'scope': 'course' if course else 'docs',
    }

    if course:
        payload['course'] = course

    return payload


def call_faq_assistant(payload):
    endpoint = faq_assistant_endpoint()
    if not endpoint:
        logger.info('FAQ_ASSISTANT_URL is not set; skipping FAQ assistant request')
        return None

    headers = {}
    if FAQ_ASSISTANT_SHARED_SECRET:
        headers['x-faq-assistant-secret'] = FAQ_ASSISTANT_SHARED_SECRET

    response = requests.post(
        endpoint, json=payload, headers=headers, timeout=FAQ_ASSISTANT_TIMEOUT
    )
    response.raise_for_status()
    return response.json()


def post_faq_assistant_answer(channel, thread_ts, payload):
    if not channel or not thread_ts:
        logger.info('FAQ assistant request missing channel or ts')
        return

    if not payload['question']:
        slack.post_message_to_thread(
            channel, thread_ts,
            'Please include a question.'
        )
        return

    logger.info(
        f"FAQ assistant request: scope={payload['scope']} "
        f"course={payload.get('course', '')}"
    )
    answer = call_faq_assistant(payload)
    if not answer:
        return

    message = answer.get('answer') or "I couldn't find an answer."
    message = slack.github_to_slack_markdown(message)
    slack.post_message_to_thread(channel, thread_ts, message)


def handle_app_mention(event):
    if event.get('bot_id'):
        logger.info('Ignoring bot app_mention')
        return

    channel = event.get('channel')
    thread_ts = event.get('thread_ts') or event.get('ts')
    payload = build_faq_assistant_payload(event)

    post_faq_assistant_answer(channel, thread_ts, payload)


def handle_faq_assistant_reaction(event, reaction_config):
    item = event.get('item') or {}
    channel = item.get('channel')
    thread_ts = item.get('ts')

    if not channel or not thread_ts:
        logger.info('faq reaction missing channel or ts')
        return

    _, original_message = slack.get_message(event)
    payload = build_faq_assistant_payload_for_question(channel, original_message)
    post_faq_assistant_answer(channel, thread_ts, payload)
    

def handle_slack_post(event, reaction_config):
    channel_id = event['item']['channel']
    channel_name = get_channel_name(channel_id)

    if 'placeholders' in reaction_config:
        message = util.format_message(
            reaction_config['message'],
            reaction_config['placeholders'],
            channel_name
        )
        if message is None:
            return
    else:
        message = reaction_config['message']
    
    slack.post_message_thread(event, message)


def handle_remove_broadcast(event, reaction_config):
    """Remove a broadcasted thread message from channel (keeps it in the thread)"""
    item = event['item']
    channel = item['channel']
    ts = item['ts']
    
    # Get message details to check if it's a broadcasted thread reply
    message_details = slack.get_message_content(channel, ts)
    if not message_details:
        logger.info(f"Message not found for {channel} {ts}")
        return
    
    # Check if this is a broadcasted thread reply
    # A broadcasted reply has thread_ts != ts (it's a reply in a thread)
    thread_ts = message_details.get('thread_ts')
    is_broadcasted_reply = thread_ts is not None and thread_ts != ts
    
    if is_broadcasted_reply:
        # Remove the broadcasted message from the channel
        # (it will still remain in the thread)
        if FAKE_DELETE:
            logger.info(f"FAKE_DELETE broadcasted message for {channel} {ts}")
        else:
            slack.remove_message(channel, ts)
        logger.info(f"Removed broadcasted message from channel {channel} (kept in thread)")
    else:
        logger.info(f"Message {ts} is not a broadcasted reply, skipping removal")


def handle_delete_message(event, reaction_config):
    """Delete a message and optionally all its thread replies, sending DMs to affected users"""
    item = event['item']
    channel = item['channel']
    ts = item['ts']
    
    # Get parent message details
    message_details = slack.get_message_content(channel, ts)
    if not message_details:
        logger.info(f"Message not found for {channel} {ts}")
        return

    user = message_details.get('user')
    original_message = message_details.get('text', '')
    # Escape curly braces in user message to avoid format string issues
    original_message = original_message.replace('{', '{{').replace('}', '}}')
    
    # Skip if there's no user (e.g., bot message or deleted message)
    if not user:
        logger.info(f"Message has no user for {channel} {ts}")
        return
    
    # Handle thread messages if thread_message is configured
    thread_message_pattern = reaction_config.get('thread_message')
    if thread_message_pattern:
        # Get thread replies
        thread_replies = slack.get_thread_replies(channel, ts)
        
        # Delete all thread replies first
        for reply in thread_replies:
            reply_user = reply.get('user')
            reply_ts = reply['ts']
            
            if reply_user:  # Only process messages with a user (not bot messages)
                # Send DM to thread reply author
                thread_values = {
                    'user': reply_user,
                    'channel': channel,
                }
                
                if 'placeholders' in reaction_config:
                    thread_values.update(reaction_config['placeholders'])
                
                thread_dm = util.format_message(thread_message_pattern, thread_values, channel)
                
                if thread_dm:
                    slack.send_dm(reply_user, thread_dm)
                
                # Delete the thread reply
                if FAKE_DELETE:
                    logger.info(f"FAKE_DELETE thread reply for {channel} {reply_ts}")
                else:
                    slack.remove_message(channel, reply_ts)
    
    # Now handle the parent message
    message_pattern = reaction_config['message']
    
    values = {
        'user': user,
        'user_message': original_message,
        'channel': channel,
    }
    
    if 'placeholders' in reaction_config:
        values.update(reaction_config['placeholders'])
    
    message_dm = util.format_message(message_pattern, values, channel)
    
    if message_dm:
        slack.send_dm(user, message_dm)
    
    # Delete the parent message
    if FAKE_DELETE:
        logger.info(f"FAKE_DELETE for {channel} {ts}")
    else:
        slack.remove_message(channel, ts)


def handle_ask_ai(event, reaction_config):
    user, original_message = slack.get_message(event)
    # Escape curly braces in user message to avoid format string issues
    original_message = original_message.replace('{', '{{').replace('}', '}}')

    prompt = reaction_config['prompt_template'].format(user_message=original_message)
    model = reaction_config['model']

    ai_response = groqu.ai_request(prompt, model)
    ai_response = slack.github_to_slack_markdown(ai_response)

    logger.info("response from GROQ: " + ai_response)

    message = reaction_config['answer_template'].format(user=user, ai_response=ai_response)

    slack.post_message_thread(event, message)


def handle_repost_to_thread_and_delete(event, reaction_config):
    """Repost the original message to the thread with a custom message, then delete from channel"""
    item = event['item']
    channel = item['channel']
    ts = item['ts']
    channel_name = get_channel_name(channel)
    
    # Get the original message content
    message_details = slack.get_message_content(channel, ts)
    if not message_details:
        logger.info(f"Message not found for {channel} {ts}")
        return
    
    user = message_details.get('user')
    original_message = message_details.get('text', '')
    
    # Skip if there's no user (e.g., bot message or deleted message)
    if not user:
        logger.info(f"Message has no user for {channel} {ts}")
        return
    
    # Escape curly braces in user message to avoid format string issues
    original_message_escaped = original_message.replace('{', '{{').replace('}', '}}')
    
    # Format the thread message with placeholders
    message_pattern = reaction_config['message']

    values = {
        'user': user,
        'user_message': original_message_escaped,
        'channel': channel,
    }

    if 'placeholders' in reaction_config:
        # Resolve channel-specific placeholders (e.g., link for the channel)
        resolved_placeholders = util.prepare_values(
            reaction_config['placeholders'],
            channel_name
        )
        if resolved_placeholders is None:
            logger.info(f"No placeholder matched for channel {channel_name}")
            return
        # Merge with values
        values.update(resolved_placeholders)

    # Format the message with all placeholders
    thread_message = util.handle_qoutes(message_pattern, values)
    thread_message = thread_message.format(**values)
    
    # Post the message to the thread
    slack.post_message_thread(event, thread_message)
    logger.info(f"Reposted message to thread for {channel} {ts}")
    
    # Delete the original message from the channel
    if FAKE_DELETE:
        logger.info(f"FAKE_DELETE for {channel} {ts}")
    else:
        slack.remove_message(channel, ts)
    logger.info(f"Deleted original message from channel {channel} (kept in thread)")


def _delete_message(channel, ts):
    if FAKE_DELETE:
        logger.info(f"FAKE_DELETE for {channel} {ts}")
        return True

    response = slack.remove_message(channel, ts)
    if isinstance(response, dict) and not response.get('ok', False):
        logger.info(
            f"delete failed for {channel} {ts}: {response.get('error')}"
        )
        return False

    return True


def _message_key(message):
    channel = message.get('channel')
    if isinstance(channel, dict):
        channel = channel.get('id')

    return channel, message.get('ts')


def _seed_ban_message(channel, ts, message_details):
    seed = {
        'channel': {'id': channel},
        'ts': ts,
        'text': message_details.get('text', ''),
    }

    thread_ts = message_details.get('thread_ts')
    if thread_ts:
        seed['thread_ts'] = thread_ts

    return seed


def _format_reply_notification(template, reply_user, channel, reply_text):
    escaped = reply_text.replace('{', '{{').replace('}', '}}')
    values = {
        'user': reply_user,
        'channel': channel,
        'user_message': escaped,
    }
    rendered = util.handle_qoutes(template, values)
    return rendered.format(**values)


def _format_admin_summary(template, target_user_id, user_info, parent_deleted,
                         replies_deleted, admin_url):
    profile = (user_info or {}).get('profile', {})
    updated_ts = (user_info or {}).get('updated')
    updated_str = datetime.utcfromtimestamp(updated_ts).strftime('%Y-%m-%d') if updated_ts else 'unknown'

    values = {
        'target_user': target_user_id,
        'target_user_id': target_user_id,
        'display_name': profile.get('display_name') or '',
        'real_name': profile.get('real_name') or '',
        'email': profile.get('email') or '',
        'updated': updated_str,
        'deleted_count': parent_deleted,
        'thread_deleted_count': replies_deleted,
        'admin_url': admin_url,
    }
    return template.format(**values)


def _build_admin_summary_blocks(summary, target_user_id, admin_url):
    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": summary},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Target user ID for copying:*\n```{target_user_id}```",
            },
        },
    ]

    if admin_url:
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "Open admin members"},
                "url": admin_url,
                "action_id": "open_admin_members",
                "value": target_user_id,
                "style": "primary",
            }],
        })

    return blocks


def handle_ban_user(event, reaction_config):
    """Delete recent messages from a spammer (no DM to them),
    notify innocent thread participants, and DM the reacting moderator
    with a cleanup summary and admin-panel link."""
    item = event['item']
    channel = item['channel']
    ts = item['ts']
    moderator = event.get('user')

    message_details = slack.get_message_content(channel, ts)
    if not message_details:
        logger.info(f"Ban: reacted message not found for {channel} {ts}")
        return

    target_user_id = message_details.get('user')
    if not target_user_id:
        logger.info("Ban: reacted message has no user; aborting")
        return

    if target_user_id in set(config.get('admins', [])):
        logger.info(f"Ban: refusing to act on admin {target_user_id}")
        return

    user_info = slack.get_user_info(target_user_id) or {}
    username = user_info.get('name') or user_info.get('profile', {}).get('display_name')

    lookback_hours = int(reaction_config.get('lookback_hours', 24))
    # search.messages 'after:' is day-granular and exclusive; pad by 1 day
    # and then filter by exact timestamp to honor lookback_hours precisely.
    pad_days = lookback_hours // 24 + 1
    after_date = (datetime.utcnow() - timedelta(days=pad_days)).strftime('%Y-%m-%d')
    cutoff_ts = time.time() - lookback_hours * 3600

    search_matches = []
    if username:
        search_matches = slack.search_user_messages(username, after_date)
        search_matches = [
            m for m in search_matches
            if float(m.get('ts', 0)) >= cutoff_ts
        ]
        logger.info(
            f"Ban: found {len(search_matches)} messages for @{username} "
            f"since {after_date}"
        )
    else:
        logger.info(f"Ban: could not resolve username for {target_user_id}; deleting reacted message only")

    matches = [_seed_ban_message(channel, ts, message_details)]
    seen = {_message_key(matches[0])}
    for match in search_matches:
        key = _message_key(match)
        if key not in seen:
            matches.append(match)
            seen.add(key)

    reply_template = reaction_config.get('reply_message')
    deleted = set()
    parent_deleted = 0
    replies_deleted = 0

    for msg in matches:
        msg_channel = (msg.get('channel') or {}).get('id')
        msg_ts = msg.get('ts')
        if not msg_channel or not msg_ts:
            continue

        thread_ts = msg.get('thread_ts')
        is_parent = (not thread_ts) or (thread_ts == msg_ts)

        if is_parent:
            for reply in slack.get_thread_replies(msg_channel, msg_ts):
                reply_ts = reply['ts']
                reply_user = reply.get('user')
                key = (msg_channel, reply_ts)
                if key in deleted:
                    continue

                if reply_user and reply_user != target_user_id and reply_template:
                    notification = _format_reply_notification(
                        reply_template, reply_user, msg_channel,
                        reply.get('text', '')
                    )
                    slack.send_dm(reply_user, notification)

                if _delete_message(msg_channel, reply_ts):
                    deleted.add(key)
                    replies_deleted += 1

        key = (msg_channel, msg_ts)
        if key in deleted:
            continue
        if _delete_message(msg_channel, msg_ts):
            deleted.add(key)
            parent_deleted += 1

    admin_template = reaction_config.get('admin_message')
    if admin_template and moderator:
        admin_url = (config.get('workspace') or {}).get('admin_users_url', '')
        summary = _format_admin_summary(
            admin_template, target_user_id, user_info,
            parent_deleted, replies_deleted, admin_url
        )
        blocks = _build_admin_summary_blocks(summary, target_user_id, admin_url)
        slack.send_dm_blocks(moderator, summary, blocks)
        slack.send_dm(moderator, target_user_id)


action_handlers = {
    'SLACK_POST': handle_slack_post,
    'DELETE_MESSAGE': handle_delete_message,
    'ASK_AI': handle_ask_ai,
    'FAQ_ASSISTANT': handle_faq_assistant_reaction,
    'REMOVE_BROADCAST': handle_remove_broadcast,
    'REPOST_TO_THREAD_AND_DELETE': handle_repost_to_thread_and_delete,
    'BAN_USER': handle_ban_user,
}


def process_reaction(body, event):
    reaction = event['reaction']

    if reaction not in reaction_configs:
        logger.info(f"no reaction config for {reaction}")
        return

    reaction_config = reaction_configs[reaction]

    # Support both single type and list of types (multiple handlers)
    action_types = reaction_config.get('types') or [reaction_config.get('type')]
    
    if not action_types or not any(action_types):
        logger.info(f"no action type configured for {reaction}")
        return
    
    # Execute all handlers in sequence
    for action_type in action_types:
        if not action_type:
            continue
        
        action_handler = action_handlers.get(action_type)
        
        if action_handler:
            action_handler(event, reaction_config)
        else:
            logger.info(f"no handler for {action_type}")


def run(body):
    print(json.dumps(body))
    event = body['event']
    event_type = event.get('type')

    if event_type == 'app_mention':
        handle_app_mention(event)
        return

    if event_type == 'reaction_added':
        logger.info(f'reaction: {event["reaction"]}')
        process_reaction(body, event)
        return

    logger.info(f'unsupported event type: {event_type}')


def lambda_handler(event, context):
    run(event)
    return {
        'statusCode': 200,
        'body': "done"
    }
