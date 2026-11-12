import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / 'scripts' / 'prove_cmp_slack.py'
spec = importlib.util.spec_from_file_location('cmp_proof', path)
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)


class TestLiveProofSlackTransport(unittest.TestCase):
    @patch.object(proof.requests, 'post')
    @patch.object(proof.requests, 'get')
    def test_thread_history_uses_get_query_parameters(self, get, post):
        get.return_value.json.return_value = {'ok': True, 'messages': []}
        proof.slack_call('test-user-token', 'conversations.replies', channel='C123', ts='123.1')
        get.assert_called_once_with(
            'https://slack.com/api/conversations.replies',
            params={'channel': 'C123', 'ts': '123.1'},
            headers={'Authorization': 'Bearer test-user-token'}, timeout=(3, 10),
        )
        post.assert_not_called()

    @patch.object(proof.requests, 'post')
    def test_message_post_uses_json(self, post):
        post.return_value.json.return_value = {'ok': True}
        proof.slack_call('test-user-token', 'chat.postMessage', channel='C123', text='test')
        self.assertEqual(post.call_args.kwargs['json'], {'channel': 'C123', 'text': 'test'})

    @patch.object(proof.requests, 'get')
    def test_failed_history_is_reported(self, get):
        get.return_value.json.return_value = {'ok': False, 'error': 'missing_scope'}
        with self.assertRaisesRegex(RuntimeError, 'missing_scope'):
            proof.slack_call('test-user-token', 'conversations.replies', channel='C123', ts='123.1')

    @patch.dict(os.environ, {'PROOF_THREAD_TS': '123.1'})
    @patch.object(proof, 'slack_call')
    @patch.object(proof.requests, 'get')
    @patch.object(proof.boto3, 'client')
    def test_reuses_thread_and_reads_with_bot_history_capability(self, client, get, call):
        client.return_value.get_function_configuration.return_value = {'Environment': {'Variables': {
            'CMP_CONTEXT_ENABLED': '1', 'CMP_BOT_READ_TOKEN': 'cmp',
            'SLACK_TOKEN': 'bot', 'USER_SLACK_TOKEN': 'user', 'CMP_SLACK_TEAM_ID': 'T123',
        }}}
        get.return_value.json.return_value = {'projects': []}

        def api(token, method, **payload):
            if method == 'auth.test':
                return {'team_id': 'T123', 'user_id': 'UBOT' if token == 'bot' else 'U123'}
            if method == 'conversations.replies':
                self.assertEqual(token, 'bot')
                self.assertEqual(payload['ts'], '123.1')
                return {'messages': [{'ts': '123.2', 'user': 'UBOT', 'text':
                    'Peer review assignments have not been created. https://courses.datatalks.club/ml-zoomcamp-2026/'}]}
            self.fail('Existing proof thread must not post another question')

        call.side_effect = api
        proof.main()
        self.assertEqual(call.call_count, 3)
