import json
import base64

import boto3


lambda_client = boto3.client('lambda')


admins = {'U01AXE0P5M3'}


def extract_body(event):
    if 'body' not in event:
        return {}
    
    raw = event['body']
    
    base64_needed = event.get('isBase64Encoded', False)
    if base64_needed:
        raw = base64.b64decode(raw).decode('utf-8')

    # Check if this is an interactive component (form-encoded)
    if 'payload=' in raw:
        # Extract the payload parameter from form-encoded data
        import urllib.parse
        parsed = urllib.parse.parse_qs(raw)
        if 'payload' in parsed:
            payload_str = parsed['payload'][0]
            return {'payload': payload_str}
    
    decoded = json.loads(raw)
    return decoded


def challenge(body):
    challenge_answer = body.get("challenge")

    return {
        'statusCode': 200,
        'body': challenge_answer
    }


def run(body):
    print(json.dumps(body))

    if 'challenge' in body:
        return challenge(body)
    
    # Handle interactive components (button clicks)
    if 'payload' in body:
        lambda_client.invoke(
            FunctionName='automator-message-moderator',
            InvocationType='Event',
            Payload=json.dumps(body)
        )
        return {
            'statusCode': 200,
            'body': json.dumps({'ok': True})
        }

    event = body.get('event', {})
    event_user = event.get('user')
    event_type = event.get('type')

    print(f'user: {event_user} (admin: {event_user in admins}), event_type: {event_type}')

    if (event_type == 'reaction_added') and (event_user in admins):
        lambda_client.invoke(
            FunctionName='automator-process-reaction',
            InvocationType='Event',
            Payload=json.dumps(body)
        )

    if event_type == 'app_mention':
        lambda_client.invoke(
            FunctionName='automator-process-reaction',
            InvocationType='Event',
            Payload=json.dumps(body)
        )
    
    # Route message events to moderator lambda
    if event_type == 'message':
        lambda_client.invoke(
            FunctionName='automator-message-moderator',
            InvocationType='Event',
            Payload=json.dumps(body)
        )

    return {
        'statusCode': 200,
        'body': "Hello from lambda!"
    }


def lambda_handler(original_event, context):
    body = extract_body(original_event)
    return run(body)
