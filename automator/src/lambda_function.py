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
import audit
import spam
from logs import logger


FAKE_DELETE = os.getenv('FAKE_DELETE', '0') == '1'
CONFIG_FILE = os.getenv('CONFIG_FILE', 'config.yaml')
FAQ_ASSISTANT_URL = os.getenv('FAQ_ASSISTANT_URL', '').strip()
FAQ_ASSISTANT_SHARED_SECRET = os.getenv('FAQ_ASSISTANT_SHARED_SECRET', '')
FAQ_ASSISTANT_TIMEOUT = int(os.getenv('FAQ_ASSISTANT_TIMEOUT', '55'))
FAQ_ASSISTANT_ERROR_MESSAGE = (
    'The FAQ assistant is currently not available. '
    'In the meantime, you can try to find the answer here:'
)
FAQ_ASSISTANT_GENERIC_RESOURCES = {
    'docs': 'https://datatalks.club/docs/',
    'faq': 'https://datatalks.club/faq/',
}



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
        user=event.get('user'),
    )


def build_faq_assistant_payload_for_question(channel, question, user=None):
    course = course_for_channel(channel)
    payload = {
        'question': clean_app_mention_text(question),
        'scope': 'course' if course else 'docs',
    }

    if course:
        payload['course'] = course
    if channel:
        payload['channel'] = channel
    if user:
        payload['user'] = user

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


def faq_assistant_fallback_resources(payload):
    course = payload.get('course')
    if not course:
        return FAQ_ASSISTANT_GENERIC_RESOURCES

    return {
        'docs': f'https://datatalks.club/docs/courses/{course}/',
        'faq': f'https://datatalks.club/faq/{course}.html',
        'repo': f'https://github.com/DataTalksClub/{course}',
    }


def format_faq_assistant_error_message(payload):
    resources = faq_assistant_fallback_resources(payload)
    lines = [
        f"- <{resources['docs']}|Docs>",
        f"- <{resources['faq']}|FAQ>",
    ]
    if resources.get('repo'):
        lines.append(f"- <{resources['repo']}|Course repo>")

    return (
        f'{FAQ_ASSISTANT_ERROR_MESSAGE}\n\n'
        + '\n'.join(lines)
    )


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
    try:
        answer = call_faq_assistant(payload)
    except requests.RequestException as exc:
        response = getattr(exc, 'response', None)
        status = getattr(response, 'status_code', None)
        body = getattr(response, 'text', '') if response is not None else ''
        logger.info(
            f"FAQ assistant request failed: status={status} "
            f"error={exc} body={body[:500]}"
        )
        slack.post_message_to_thread(
            channel, thread_ts, format_faq_assistant_error_message(payload)
        )
        return

    if not answer:
        return

    message = answer.get('answer') or "I couldn't find an answer."
    message = slack.github_to_slack_markdown(message)
    message += format_faq_sources(answer.get('sources'), answer.get('found_answer', True))
    slack.post_message_to_thread(channel, thread_ts, message)


# Display labels for the FAQ assistant's structured `source` types.
FAQ_SOURCE_LABELS = {'faq': 'FAQ', 'docs': 'docs', 'course-repo': 'repo'}


def format_faq_sources(sources, found_answer=True):
    """Render the FAQ assistant's structured sources as Slack mrkdwn links.

    When the assistant found an answer these are its citations; otherwise they are
    suggested resources, so the heading changes accordingly. Each line is prefixed
    with the source type (FAQ / docs / repo) so the reader can tell how authoritative
    it is.
    """
    lines = []
    for source in (sources or []):
        if not source.get('url'):
            continue
        title = source.get('title') or source.get('source') or 'source'
        kind = source.get('source')
        label = FAQ_SOURCE_LABELS.get(kind, kind)
        prefix = f'[{label}] ' if label else ''
        lines.append(f"• {prefix}<{source['url']}|{title}>")
    if not lines:
        return ''
    heading = '*Sources:*' if found_answer else '*You can check these for more information:*'
    return f'\n\n{heading}\n' + '\n'.join(lines)


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
    payload = build_faq_assistant_payload_for_question(
        channel, original_message, user=event.get('user'))
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
        ok = _delete_message(channel, ts)
        logger.info(f"Removed broadcasted message from channel {channel} (kept in thread)")
        _record_delete_action(
            event,
            'REMOVE_BROADCAST',
            [_deleted_entry(
                channel, ts, message_details.get('user'),
                message_details.get('text', ''), 'broadcast', ok,
            )],
            target_user_id=message_details.get('user'),
        )
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
    original_message_raw = message_details.get('text', '')
    # Escape curly braces in user message to avoid format string issues
    original_message = original_message_raw.replace('{', '{{').replace('}', '}}')
    
    # Skip if there's no user (e.g., bot message or deleted message)
    if not user:
        logger.info(f"Message has no user for {channel} {ts}")
        return

    deleted_messages = []
    
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
                
                ok = _delete_message(channel, reply_ts)
                deleted_messages.append(_deleted_entry(
                    channel, reply_ts, reply_user, reply.get('text', ''),
                    'reply', ok,
                ))
    
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
    
    ok = _delete_message(channel, ts)
    deleted_messages.append(_deleted_entry(
        channel, ts, user, original_message_raw, 'parent', ok,
    ))
    _record_delete_action(
        event,
        'DELETE_MESSAGE',
        deleted_messages,
        target_user_id=user,
    )


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
    
    ok = _delete_message(channel, ts)
    logger.info(f"Deleted original message from channel {channel} (kept in thread)")
    _record_delete_action(
        event,
        'REPOST_TO_THREAD_AND_DELETE',
        [_deleted_entry(channel, ts, user, original_message, 'parent', ok)],
        target_user_id=user,
    )


def _deleted_entry(channel, ts, user=None, text='', kind='parent', ok=True):
    return {
        'channel': channel,
        'ts': ts,
        'user': user,
        'text': text,
        'kind': kind,
        'ok': ok,
        'fake': FAKE_DELETE,
    }


def _record_delete_action(event, action_type, deleted_messages, **kwargs):
    try:
        audit.record_delete_action(
            event,
            action_type,
            deleted_messages,
            channel_name=get_channel_name((event.get('item') or {}).get('channel')),
            fake_delete=FAKE_DELETE,
            **kwargs,
        )
    except Exception as exc:
        logger.info(f"delete audit failed: {exc}")


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
                         replies_deleted, admin_url, extra_values=None):
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
    if extra_values:
        values.update(extra_values)
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


def _cleanup_user_message_matches(matches, target_user_id, reply_template):
    deleted = set()
    parent_deleted = 0
    replies_deleted = 0
    deleted_messages = []

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

                ok = _delete_message(msg_channel, reply_ts)
                deleted_messages.append(_deleted_entry(
                    msg_channel, reply_ts, reply_user, reply.get('text', ''),
                    'reply', ok,
                ))
                if ok:
                    deleted.add(key)
                    replies_deleted += 1

        key = (msg_channel, msg_ts)
        if key in deleted:
            continue
        kind = 'parent' if is_parent else 'reply'
        ok = _delete_message(msg_channel, msg_ts)
        deleted_messages.append(_deleted_entry(
            msg_channel, msg_ts, target_user_id, msg.get('text', ''),
            kind, ok,
        ))
        if ok:
            deleted.add(key)
            parent_deleted += 1

    return parent_deleted, replies_deleted, deleted_messages


def _notify_admins_of_cleanup(admin_ids, admin_template, target_user_id,
                              user_info, parent_deleted, replies_deleted,
                              extra_values=None):
    if not admin_template or not admin_ids:
        return
    admin_url = (config.get('workspace') or {}).get('admin_users_url', '')
    summary = _format_admin_summary(
        admin_template, target_user_id, user_info,
        parent_deleted, replies_deleted, admin_url, extra_values=extra_values,
    )
    blocks = _build_admin_summary_blocks(summary, target_user_id, admin_url)
    for admin_id in admin_ids:
        slack.send_dm_blocks(admin_id, summary, blocks)
        slack.send_dm(admin_id, target_user_id)


def _tracked_to_search_match(entry):
    match = {
        'channel': {'id': entry.get('channel')},
        'ts': entry.get('ts'),
        'text': entry.get('text') or '',
    }
    thread_ts = entry.get('thread_ts')
    if thread_ts:
        match['thread_ts'] = thread_ts
    return match


def flush_cross_channel_spam(payload, *, now=None, store=None):
    """Wipe a quiet cross-channel spam session and DM admins like :ban-user:."""
    user_id = payload.get('user_id')
    fp = payload.get('fingerprint')
    if not user_id or not fp:
        return

    hooks = store or {}
    load = hooks.get('load_session') or spam.load_session
    delete = hooks.get('delete_session') or spam.delete_session

    try:
        item = load(user_id, fp)
    except Exception as exc:
        logger.info(f"spam flush load failed: {exc}")
        return

    if not item:
        logger.info(f"spam flush: no session user={user_id} fp={fp}")
        return
    if item.get('status') == 'done':
        return

    now = now if now is not None else time.time()
    quiet = spam.quiet_seconds(config)
    last_seen = float(item.get('last_seen') or 0)
    if last_seen and (now - last_seen) < quiet - 1:
        logger.info(f"spam flush: still posting user={user_id}")
        return

    if user_id in set(config.get('admins', [])):
        logger.info(f"spam flush: refusing admin {user_id}")
        return

    spam_cfg = spam.tracker_config(config)
    ban_cfg = reaction_configs.get('ban-user') or {}
    reply_template = spam_cfg.get('reply_message') or ban_cfg.get('reply_message')
    admin_template = spam_cfg.get('admin_message') or ban_cfg.get('admin_message')
    lookback_hours = int(spam_cfg.get('lookback_hours') or ban_cfg.get('lookback_hours') or 24)
    threshold = spam.similarity_threshold(config)
    canonical = item.get('canonical_text') or ''

    user_info = slack.get_user_info(user_id) or {}
    username = user_info.get('name') or (user_info.get('profile') or {}).get('display_name')

    matches = []
    seen = set()
    for entry in item.get('messages') or []:
        match = _tracked_to_search_match(entry)
        key = _message_key(match)
        if None in key or key in seen:
            continue
        matches.append(match)
        seen.add(key)

    if username:
        pad_days = lookback_hours // 24 + 1
        after_date = (datetime.utcnow() - timedelta(days=pad_days)).strftime('%Y-%m-%d')
        cutoff_ts = now - lookback_hours * 3600
        for found in slack.search_user_messages(username, after_date):
            if float(found.get('ts') or 0) < cutoff_ts:
                continue
            if not spam.is_similar(found.get('text') or '', canonical, threshold):
                continue
            key = _message_key(found)
            if key in seen:
                continue
            matches.append(found)
            seen.add(key)

    parent_deleted, replies_deleted, deleted_messages = (
        _cleanup_user_message_matches(matches, user_id, reply_template)
    )

    first = (item.get('messages') or [{}])[0]
    audit_event = {
        'user': 'spam-tracker',
        'reaction': 'cross-channel-spam',
        'event_ts': str(now),
        'item': {
            'channel': first.get('channel'),
            'ts': first.get('ts'),
        },
        'item_user': user_id,
    }
    channels = sorted(spam.unique_channels(item.get('messages') or []))
    _record_delete_action(
        audit_event,
        'CROSS_CHANNEL_SPAM',
        deleted_messages,
        target_user_id=user_id,
        target_user={
            'id': user_id,
            'name': username,
            'display_name': (user_info.get('profile') or {}).get('display_name') or '',
            'real_name': (user_info.get('profile') or {}).get('real_name') or '',
            'email': (user_info.get('profile') or {}).get('email') or '',
        },
        extra={
            'lookback_hours': lookback_hours,
            'parent_deleted': parent_deleted,
            'replies_deleted': replies_deleted,
            'channel_count': len(channels),
            'fingerprint': fp,
        },
    )

    admin_ids = spam_cfg.get('admin_users') or config.get('admins') or []
    channel_list = ' '.join(f'<#{cid}>' for cid in channels)
    _notify_admins_of_cleanup(
        admin_ids, admin_template, user_id, user_info,
        parent_deleted, replies_deleted,
        extra_values={
            'channel_count': len(channels),
            'channel_list': channel_list,
            'sample_text': canonical[:500],
        },
    )

    try:
        delete(user_id, fp)
    except Exception as exc:
        logger.info(f"spam flush delete session failed: {exc}")


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
    parent_deleted, replies_deleted, deleted_messages = (
        _cleanup_user_message_matches(matches, target_user_id, reply_template)
    )

    _record_delete_action(
        event,
        'BAN_USER',
        deleted_messages,
        target_user_id=target_user_id,
        target_user={
            'id': target_user_id,
            'name': username,
            'display_name': (user_info.get('profile') or {}).get('display_name') or '',
            'real_name': (user_info.get('profile') or {}).get('real_name') or '',
            'email': (user_info.get('profile') or {}).get('email') or '',
        },
        extra={
            'lookback_hours': lookback_hours,
            'parent_deleted': parent_deleted,
            'replies_deleted': replies_deleted,
            'search_match_count': len(search_matches),
        },
    )

    admin_template = reaction_config.get('admin_message')
    if admin_template and moderator:
        _notify_admins_of_cleanup(
            [moderator], admin_template, target_user_id, user_info,
            parent_deleted, replies_deleted,
        )


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

    if event_type == 'message':
        spam.ingest_message(event, config)
        return

    logger.info(f'unsupported event type: {event_type}')


def flush_quiet_spam_sessions(*, now=None, store=None):
    """Scheduled scan: flush ready aggregates that have been quiet long enough."""
    now = now if now is not None else time.time()
    cutoff = int(now) - spam.quiet_seconds(config)
    hooks = store or {}
    list_ready = hooks.get('list_ready_sessions') or spam.list_ready_sessions
    try:
        items = list_ready(cutoff)
    except Exception as exc:
        logger.info(f"spam scan load failed: {exc}")
        return
    logger.info(f"spam scan: {len(items)} quiet aggregate(s) cutoff={cutoff}")
    for item in items:
        flush_cross_channel_spam(
            {
                'user_id': item.get('user_id'),
                'fingerprint': item.get('fingerprint'),
            },
            now=now,
            store=store,
        )


def lambda_handler(event, context):
    if isinstance(event, dict) and event.get('action') == 'spam_quiet_scan':
        flush_quiet_spam_sessions()
        return {
            'statusCode': 200,
            'body': "done"
        }

    run(event)
    return {
        'statusCode': 200,
        'body': "done"
    }
