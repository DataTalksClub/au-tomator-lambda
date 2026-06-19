import os
import requests


SLACK_TOKEN = os.getenv('SLACK_TOKEN')
USER_SLACK_TOKEN = os.getenv('USER_SLACK_TOKEN')
ADMIN_USER_ID = os.getenv('ADMIN_USER_ID', 'U01AXE0P5M3')


def send_moderation_alert(user_id, messages):
    """
    Send a moderation alert to the admin with interactive buttons.
    
    Args:
        user_id: The user who exceeded the message threshold
        messages: List of message details
    """
    url = 'https://slack.com/api/chat.postMessage'
    
    # Build message blocks
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "⚠️ Message Rate Limit Exceeded"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"User <@{user_id}> has posted {len(messages)} messages in the last 3 minutes."
            }
        },
        {
            "type": "divider"
        }
    ]
    
    # Add message previews
    for i, msg in enumerate(messages[:5], 1):  # Show up to 5 messages
        channel_id = msg.get('channel_id', 'unknown')
        message_text = msg.get('message_text', '')[:200]  # Limit preview length
        
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Message {i}* in <#{channel_id}>:\n>{message_text}"
            }
        })
    
    if len(messages) > 5:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"_...and {len(messages) - 5} more messages_"
            }
        })
    
    blocks.append({"type": "divider"})
    
    # Add action buttons
    blocks.append({
        "type": "actions",
        "block_id": "moderation_actions",
        "elements": [
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "🗑️ Delete All Messages"
                },
                "style": "danger",
                "value": user_id,
                "action_id": "delete_messages"
            },
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "🚫 Deactivate User"
                },
                "style": "danger",
                "value": user_id,
                "action_id": "deactivate_user",
                "confirm": {
                    "title": {
                        "type": "plain_text",
                        "text": "Are you sure?"
                    },
                    "text": {
                        "type": "mrkdwn",
                        "text": f"This will deactivate user <@{user_id}>. This action cannot be undone from this interface."
                    },
                    "confirm": {
                        "type": "plain_text",
                        "text": "Deactivate"
                    },
                    "deny": {
                        "type": "plain_text",
                        "text": "Cancel"
                    }
                }
            },
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "✅ Ignore"
                },
                "value": user_id,
                "action_id": "ignore_alert"
            }
        ]
    })
    
    message_request = {
        "channel": ADMIN_USER_ID,
        "blocks": blocks,
        "text": f"Message rate limit exceeded for user {user_id}"
    }
    
    headers = {
        'Authorization': f'Bearer {SLACK_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    response = requests.post(url, json=message_request, headers=headers)
    response.raise_for_status()
    return response.json()


def delete_messages(messages):
    """
    Delete multiple messages.
    
    Args:
        messages: List of message details with channel_id and message_ts
    
    Returns:
        dict: Results of deletion attempts
    """
    url = 'https://slack.com/api/chat.delete'
    headers = {
        'Authorization': f'Bearer {USER_SLACK_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    results = {
        'success': [],
        'failed': []
    }
    
    for msg in messages:
        channel_id = msg.get('channel_id')
        message_ts = msg.get('message_ts')
        
        if not channel_id or not message_ts:
            results['failed'].append(msg)
            continue
        
        message_request = {
            "channel": channel_id,
            "ts": message_ts
        }
        
        try:
            response = requests.post(url, json=message_request, headers=headers)
            response.raise_for_status()
            response_json = response.json()
            
            if response_json.get('ok'):
                results['success'].append(msg)
            else:
                results['failed'].append(msg)
        except Exception as e:
            print(f"Error deleting message: {e}")
            results['failed'].append(msg)
    
    return results


def deactivate_user(user_id):
    """
    Deactivate a user (using admin.users.session.invalidate API).
    Note: This requires admin privileges and the admin.users.session:write scope.
    
    Alternative: Use admin.users.setInactive if you need to fully deactivate the account,
    which requires the admin.users:write scope and Slack Enterprise Grid.
    
    For most use cases, invalidating the session is sufficient and more widely available.
    
    Args:
        user_id: The user ID to deactivate
    
    Returns:
        dict: API response
    """
    # Use session invalidation as it's more widely available
    url = 'https://slack.com/api/admin.users.session.invalidate'
    
    headers = {
        'Authorization': f'Bearer {USER_SLACK_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        'user_id': user_id,
        'team_id': os.getenv('SLACK_TEAM_ID')  # Required for session invalidation
    }
    
    response = requests.post(url, json=payload, headers=headers)
    response.raise_for_status()
    return response.json()


def update_alert_message(channel, message_ts, new_text):
    """Update the alert message with results"""
    url = 'https://slack.com/api/chat.update'
    
    headers = {
        'Authorization': f'Bearer {SLACK_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        'channel': channel,
        'ts': message_ts,
        'text': new_text,
        'blocks': [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": new_text
                }
            }
        ]
    }
    
    response = requests.post(url, json=payload, headers=headers)
    response.raise_for_status()
    return response.json()
