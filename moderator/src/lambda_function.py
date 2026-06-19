import json
import os
import message_tracker
import slack_moderator


ADMIN_USER_ID = os.getenv('ADMIN_USER_ID', 'U01AXE0P5M3')


def handle_message_event(event):
    """
    Handle incoming message events from Slack.
    Track messages and alert admin if threshold exceeded.
    """
    event_type = event.get('type')
    
    # Ignore bot messages and message changes
    if event.get('subtype') in ['bot_message', 'message_changed', 'message_deleted']:
        return
    
    # Ignore admin messages
    user_id = event.get('user')
    if not user_id or user_id == ADMIN_USER_ID:
        return
    
    channel_id = event.get('channel')
    message_ts = event.get('ts')
    message_text = event.get('text', '')
    
    # Track the message
    result = message_tracker.track_message(user_id, channel_id, message_ts, message_text)
    
    # If threshold exceeded, send alert to admin
    if result['exceeded']:
        print(f"User {user_id} exceeded message threshold: {result['message_count']} messages")
        slack_moderator.send_moderation_alert(user_id, result['messages'])


def handle_interactive_action(payload):
    """
    Handle interactive button clicks from the admin alert.
    """
    action = payload['actions'][0]
    action_id = action['action_id']
    user_id = action['value']
    
    # Get channel and message_ts for updating the alert
    container = payload.get('container', {})
    response_channel = payload['channel']['id']
    response_message_ts = container.get('message_ts')
    
    if action_id == 'delete_messages':
        # Get user's tracked messages and delete them
        messages = message_tracker.get_user_messages(user_id)
        
        if messages:
            result = slack_moderator.delete_messages(messages)
            
            # Clear tracked messages
            message_tracker.clear_user_messages(user_id)
            
            # Update the alert message
            success_count = len(result['success'])
            failed_count = len(result['failed'])
            update_text = f"✅ Deleted {success_count} messages for <@{user_id}>."
            if failed_count > 0:
                update_text += f" Failed to delete {failed_count} messages."
            
            slack_moderator.update_alert_message(
                response_channel,
                response_message_ts,
                update_text
            )
        else:
            slack_moderator.update_alert_message(
                response_channel,
                response_message_ts,
                f"No messages found for <@{user_id}>."
            )
    
    elif action_id == 'deactivate_user':
        # Deactivate the user
        try:
            result = slack_moderator.deactivate_user(user_id)
            
            if result.get('ok'):
                # Also clear their tracked messages
                message_tracker.clear_user_messages(user_id)
                
                slack_moderator.update_alert_message(
                    response_channel,
                    response_message_ts,
                    f"✅ User <@{user_id}> has been deactivated."
                )
            else:
                error = result.get('error', 'unknown error')
                slack_moderator.update_alert_message(
                    response_channel,
                    response_message_ts,
                    f"❌ Failed to deactivate user <@{user_id}>: {error}"
                )
        except Exception as e:
            print(f"Error deactivating user: {e}")
            slack_moderator.update_alert_message(
                response_channel,
                response_message_ts,
                f"❌ Error deactivating user <@{user_id}>: {str(e)}"
            )
    
    elif action_id == 'ignore_alert':
        # Just clear the tracked messages for this user
        message_tracker.clear_user_messages(user_id)
        
        slack_moderator.update_alert_message(
            response_channel,
            response_message_ts,
            f"Alert ignored for <@{user_id}>. Tracked messages cleared."
        )


def lambda_handler(event, context):
    """
    Main Lambda handler for message moderation.
    Handles both message events and interactive actions.
    """
    print(json.dumps(event))
    
    # Handle URL verification challenge
    if 'challenge' in event:
        return {
            'statusCode': 200,
            'body': event['challenge']
        }
    
    # Check if this is an interactive action (button click)
    if 'payload' in event:
        # Parse the payload (it comes as a string in the event)
        payload = json.loads(event['payload'])
        handle_interactive_action(payload)
        
        return {
            'statusCode': 200,
            'body': json.dumps({'ok': True})
        }
    
    # Handle Slack event
    event_wrapper = event.get('event', {})
    event_type = event_wrapper.get('type')
    
    if event_type == 'message':
        handle_message_event(event_wrapper)
    
    return {
        'statusCode': 200,
        'body': json.dumps({'ok': True})
    }
