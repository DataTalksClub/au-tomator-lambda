import os
import time
from datetime import datetime, timedelta
import boto3
from botocore.exceptions import ClientError


DYNAMODB_ENDPOINT = os.getenv('DYNAMODB_ENDPOINT', None)
TABLE_NAME = os.getenv('MESSAGE_TRACKER_TABLE', 'slack-message-tracker')
MESSAGE_THRESHOLD = int(os.getenv('MESSAGE_THRESHOLD', '5'))
TIME_WINDOW_SECONDS = int(os.getenv('TIME_WINDOW_SECONDS', '180'))  # 3 minutes


def get_dynamodb_resource():
    """Get DynamoDB resource, supporting LocalStack for testing"""
    if DYNAMODB_ENDPOINT:
        return boto3.resource(
            'dynamodb',
            endpoint_url=DYNAMODB_ENDPOINT,
            region_name='us-east-1',
            aws_access_key_id='test',
            aws_secret_access_key='test'
        )
    return boto3.resource('dynamodb')


def ensure_table_exists():
    """Create the DynamoDB table if it doesn't exist"""
    dynamodb = get_dynamodb_resource()
    
    try:
        table = dynamodb.Table(TABLE_NAME)
        table.load()
        return table
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            # Create table
            table = dynamodb.create_table(
                TableName=TABLE_NAME,
                KeySchema=[
                    {'AttributeName': 'user_id', 'KeyType': 'HASH'},
                ],
                AttributeDefinitions=[
                    {'AttributeName': 'user_id', 'AttributeType': 'S'},
                ],
                BillingMode='PAY_PER_REQUEST'
            )
            table.wait_until_exists()
            return table
        raise


def track_message(user_id, channel_id, message_ts, message_text):
    """
    Track a new message from a user and check if they've exceeded the threshold.
    
    Returns:
        dict: {
            'exceeded': bool,
            'message_count': int,
            'messages': list of message details if exceeded
        }
    """
    table = ensure_table_exists()
    current_time = int(time.time())
    cutoff_time = current_time - TIME_WINDOW_SECONDS
    
    # Get user's message history
    try:
        response = table.get_item(Key={'user_id': user_id})
        item = response.get('Item', {})
        messages = item.get('messages', [])
    except ClientError:
        messages = []
    
    # Filter out old messages
    messages = [msg for msg in messages if msg['timestamp'] > cutoff_time]
    
    # Add new message
    messages.append({
        'timestamp': current_time,
        'channel_id': channel_id,
        'message_ts': message_ts,
        'message_text': message_text[:500]  # Limit text length
    })
    
    # Update DynamoDB
    table.put_item(
        Item={
            'user_id': user_id,
            'messages': messages,
            'last_updated': current_time
        }
    )
    
    # Check if threshold exceeded
    # Using >= so that exactly MESSAGE_THRESHOLD messages triggers the alert
    # e.g., if threshold is 5, then 5 or more messages will trigger
    exceeded = len(messages) >= MESSAGE_THRESHOLD
    
    return {
        'exceeded': exceeded,
        'message_count': len(messages),
        'messages': messages if exceeded else []
    }


def clear_user_messages(user_id):
    """Clear all tracked messages for a user"""
    table = ensure_table_exists()
    table.delete_item(Key={'user_id': user_id})


def get_user_messages(user_id):
    """Get all tracked messages for a user"""
    table = ensure_table_exists()
    
    try:
        response = table.get_item(Key={'user_id': user_id})
        item = response.get('Item', {})
        return item.get('messages', [])
    except ClientError:
        return []
