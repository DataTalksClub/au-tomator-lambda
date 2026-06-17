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
    os.path.dirname(__file__), '..', 'router', 'lambda_function.py'
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


if __name__ == '__main__':
    unittest.main()
