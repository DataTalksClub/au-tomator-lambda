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

    def run_main(self, client, get, call, replies, sleep=None):
        client.return_value.get_function_configuration.return_value = {'Environment': {'Variables': {
            'CMP_CONTEXT_ENABLED': '1', 'CMP_BOT_READ_TOKEN': 'cmp',
            'SLACK_TOKEN': 'bot', 'USER_SLACK_TOKEN': 'user', 'CMP_SLACK_TEAM_ID': 'T123',
        }}}
        get.return_value.json.return_value = {'projects': []}
        calls = []

        def api(token, method, **payload):
            calls.append((token, method, payload))
            if method == 'auth.test':
                if token == 'bot':
                    return {'team_id': 'T123', 'user_id': 'UBOT', 'bot_id': 'BBOT'}
                return {'team_id': 'T123', 'user_id': 'U123'}
            if method == 'bots.info':
                return {'bot': {'app_id': 'AAPP'}}
            if method == 'chat.postMessage':
                self.assertEqual(token, 'user')
                return {'ts': '123.1', 'message': {
                    'user': 'U123', 'bot_id': 'BUSERTOKEN', 'app_id': 'AAPP'}}
            if method == 'conversations.replies':
                self.assertEqual(token, 'bot')
                return {'messages': [{'ts': '123.1', 'user': 'U123'}] + replies}
            if method == 'chat.delete':
                return {'ok': True}
            self.fail(method)

        call.side_effect = api
        return calls

    @patch.object(proof.time, 'sleep')
    @patch.object(proof, 'slack_call')
    @patch.object(proof.requests, 'get')
    @patch.object(proof.boto3, 'client')
    def test_verified_answer_then_reply_and_question_are_deleted(self, client, get, call, sleep):
        calls = self.run_main(client, get, call, [{'ts': '123.2', 'user': 'UBOT', 'text':
            'Peer review assignments have not been created. https://courses.datatalks.club/ml-zoomcamp-2026/'}])
        proof.main()
        deletes = [(token, payload['ts']) for token, method, payload in calls if method == 'chat.delete']
        self.assertEqual(deletes, [('bot', '123.2'), ('user', '123.1')])

    @patch.object(proof.time, 'monotonic', side_effect=[0, 0, 200])
    @patch.object(proof.time, 'sleep')
    @patch.object(proof, 'slack_call')
    @patch.object(proof.requests, 'get')
    @patch.object(proof.boto3, 'client')
    def test_missing_answer_fails_loudly_and_still_deletes_question(
            self, client, get, call, sleep, monotonic):
        calls = self.run_main(client, get, call, [])
        with self.assertRaisesRegex(RuntimeError, 'No bot answer'):
            proof.main()
        deletes = [(token, payload['ts']) for token, method, payload in calls if method == 'chat.delete']
        self.assertEqual(deletes, [('user', '123.1')])

    @patch.object(proof.time, 'sleep')
    @patch.object(proof, 'slack_call')
    @patch.object(proof.requests, 'get')
    @patch.object(proof.boto3, 'client')
    def test_bad_answer_fails_and_is_deleted(self, client, get, call, sleep):
        calls = self.run_main(client, get, call, [{'ts': '123.2', 'user': 'UBOT', 'text': 'no idea'}])
        with self.assertRaisesRegex(RuntimeError, 'lacks factual CMP'):
            proof.main()
        deletes = [(token, payload['ts']) for token, method, payload in calls if method == 'chat.delete']
        self.assertEqual(deletes, [('bot', '123.2'), ('user', '123.1')])

    @patch.object(proof, 'slack_call')
    def test_cleanup_failure_is_reported(self, call):
        def api(token, method, **payload):
            if method == 'conversations.replies':
                return {'messages': []}
            raise RuntimeError('Slack chat.delete failed: cant_delete_message')
        call.side_effect = api
        with self.assertRaisesRegex(RuntimeError, 'cleanup failed.*cant_delete_message'):
            proof.cleanup('bot', 'user', '123.1', 'UBOT')

    @patch.object(proof, 'slack_call')
    def test_question_authorship(self, call):
        call.return_value = {'ts': '123.2', 'message': {
            'user': 'U123', 'bot_id': 'BUSERTOKEN', 'app_id': 'AAPP'}}
        self.assertEqual(proof.ask_as_user('user-token', 'U123', 'UBOT', 'AAPP'), '123.2')
        self.assertIs(call.call_args.kwargs['as_user'], True)
        call.return_value = {'ts': '123.2', 'message': {
            'user': 'U123', 'bot_id': 'BOTHER', 'app_id': 'AOTHER'}}
        with self.assertRaisesRegex(RuntimeError, 'authenticated user'):
            proof.ask_as_user('user-token', 'U123', 'UBOT', 'AAPP')
        self.assertEqual(call.call_args.args[1], 'chat.delete')
