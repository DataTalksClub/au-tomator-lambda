import importlib.util
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
