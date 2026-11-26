import json
import os
import sys
import types
import unittest
import importlib.util


class FakeLambdaClient:
    def __init__(self):
        self.invocations = []

    def invoke(self, **kwargs):
        self.invocations.append(kwargs)
        return {'StatusCode': 202}


fake_lambda_client = FakeLambdaClient()
fake_boto3 = types.SimpleNamespace(client=lambda service: fake_lambda_client)
sys.modules['boto3'] = fake_boto3

router_lambda_path = os.path.join(
    os.path.dirname(__file__), '..', 'src', 'lambda_function.py'
)
spec = importlib.util.spec_from_file_location(
    'router_lambda_function', router_lambda_path
)
lambda_function = importlib.util.module_from_spec(spec)
sys.modules['router_lambda_function'] = lambda_function
spec.loader.exec_module(lambda_function)


class TestRouterLambda(unittest.TestCase):
    def setUp(self):
        fake_lambda_client.invocations.clear()

    def test_admin_reaction_routes_to_automator(self):
        body = {
            'event': {
                'type': 'reaction_added',
                'user': 'U01AXE0P5M3',
                'reaction': 'faq',
            }
        }

        lambda_function.run(body)

        self.assertEqual(len(fake_lambda_client.invocations), 1)
        self.assertEqual(
            fake_lambda_client.invocations[0]['FunctionName'],
            'automator-process-reaction',
        )

    def test_non_admin_reaction_is_ignored(self):
        body = {
            'event': {
                'type': 'reaction_added',
                'user': 'U_NOT_ADMIN',
                'reaction': 'faq',
            }
        }

        lambda_function.run(body)

        self.assertEqual(fake_lambda_client.invocations, [])

    def test_app_mention_routes_to_automator_for_any_user(self):
        body = {
            'event': {
                'type': 'app_mention',
                'user': 'U_NOT_ADMIN',
                'channel': 'C06TEGTGM3J',
                'text': '<@UFAQBOT> Can I still join?',
            }
        }

        lambda_function.run(body)

        self.assertEqual(len(fake_lambda_client.invocations), 1)
        self.assertEqual(
            fake_lambda_client.invocations[0]['FunctionName'],
            'automator-process-reaction',
        )
        self.assertEqual(
            json.loads(fake_lambda_client.invocations[0]['Payload']),
            body,
        )

    def test_slack_timeout_retry_is_not_forwarded_twice(self):
        body = {'event': {'type': 'app_mention', 'user': 'U1', 'text': '<@UFAQBOT> hi'}}
        event = {'body': json.dumps(body), 'headers': {
            'X-Slack-Retry-Num': '1', 'X-Slack-Retry-Reason': 'http_timeout'}}
        response = lambda_function.lambda_handler(event, None)
        self.assertEqual(response['statusCode'], 200)
        self.assertEqual(fake_lambda_client.invocations, [])
        event['headers'] = {'x-slack-retry-num': '1', 'x-slack-retry-reason': 'http_error'}
        lambda_function.lambda_handler(event, None)
        self.assertEqual(len(fake_lambda_client.invocations), 1)

    def test_app_mention_in_thread_routes_to_automator(self):
        body = {
            'event': {
                'type': 'app_mention',
                'user': 'U_NOT_ADMIN',
                'channel': 'C0288NJ5XSA',
                'text': '<@UFAQBOT> 🚀',
                'ts': '1700000000.000200',
                'thread_ts': '1700000000.000100',
            }
        }

        lambda_function.run(body)

        self.assertEqual(len(fake_lambda_client.invocations), 1)
        self.assertEqual(
            fake_lambda_client.invocations[0]['FunctionName'],
            'automator-process-reaction',
        )
        self.assertEqual(
            json.loads(fake_lambda_client.invocations[0]['Payload']),
            body,
        )

    def test_bare_app_mention_in_thread_routes_to_automator(self):
        body = {
            'event': {
                'type': 'app_mention',
                'user': 'U_NOT_ADMIN',
                'channel': 'C0288NJ5XSA',
                'text': '<@UFAQBOT>',
                'ts': '1700000000.000200',
                'thread_ts': '1700000000.000100',
            }
        }

        lambda_function.run(body)

        self.assertEqual(len(fake_lambda_client.invocations), 1)
        self.assertEqual(
            fake_lambda_client.invocations[0]['FunctionName'],
            'automator-process-reaction',
        )
        self.assertEqual(
            json.loads(fake_lambda_client.invocations[0]['Payload']),
            body,
        )

    def test_message_event_is_ignored(self):
        body = {
            'event': {
                'type': 'message',
                'user': 'U_NOT_ADMIN',
                'channel': 'C06TEGTGM3J',
                'text': 'hello',
            }
        }

        lambda_function.run(body)

        self.assertEqual(fake_lambda_client.invocations, [])


if __name__ == '__main__':
    unittest.main()


def test_ban_timeout_retry_is_forwarded_when_first_delivery_may_have_failed():
    fake_lambda_client.invocations.clear()
    body = {'event_id': 'E_BAN', 'event': {'type': 'reaction_added',
        'user': 'U01AXE0P5M3', 'reaction': 'ban-user', 'item_user': 'US',
        'item': {'type': 'message', 'channel': 'C', 'ts': '100'}}}
    event = {'body': json.dumps(body), 'headers': {
        'x-slack-retry-num': '1', 'x-slack-retry-reason': 'http_timeout'}}
    assert lambda_function.lambda_handler(event, None)['statusCode'] == 200
    assert fake_lambda_client.invocations == [{'FunctionName': 'automator-process-reaction',
        'InvocationType': 'Event', 'Payload': json.dumps(body)}]


def test_rejected_async_invocation_is_not_acknowledged_as_success():
    from unittest.mock import patch
    with patch.object(fake_lambda_client, 'invoke', return_value={'StatusCode': 500}):
        with unittest.TestCase().assertRaisesRegex(RuntimeError, 'not accepted'):
            lambda_function.run({'event': {'type': 'reaction_added',
                'user': 'U01AXE0P5M3', 'reaction': 'ban-user'}})
