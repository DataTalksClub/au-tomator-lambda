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
    
    # Handle interactive components (button clicks): nothing consumes them
    # right now, so just acknowledge so Slack does not retry.
    if 'payload' in body:
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
    
    return {
        'statusCode': 200,
        'body': "Hello from lambda!"
    }


def is_timeout_retry(original_event):
    # Slack re-sends an event when the router took >3s (e.g. a cold start).
    # By then the first delivery has already been forwarded asynchronously, so
    # forwarding the retry would answer and alert twice for the same message.
    # Retries for other reasons (router errors) are still forwarded.
    headers = {k.lower(): v for k, v in (original_event.get('headers') or {}).items()}
    return (headers.get('x-slack-retry-num') is not None
            and headers.get('x-slack-retry-reason') == 'http_timeout')


def lambda_handler(original_event, context):
    if is_timeout_retry(original_event):
        print('Ignoring Slack http_timeout retry')
        return {'statusCode': 200, 'body': 'duplicate'}
    body = extract_body(original_event)
    return run(body)
