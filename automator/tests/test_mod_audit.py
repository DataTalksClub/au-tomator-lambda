import os
import sys
import unittest
import json
import subprocess
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import deletion_audit
import slack


class TestModAudit(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {
            'MOD_AUDIT_ENABLED': 'true', 'MOD_API_URL': 'https://mod.dtcdev.click',
            'MOD_API_TOKEN': 'test-only-token',
        })
        env.start()
        self.addCleanup(env.stop)
        self.record = {
            'text': 'example', 'files': [{'id': 'F1'}], 'user': 'U1',
            'channel': 'C1', 'ts': '123.456', 'thread_ts': None,
            'reacting_admin': 'UADMIN', 'reaction': 'delete',
            'timestamp': '2026-10-27T08:00:00Z',
        }

    def test_configuration_cannot_disable_audit(self):
        for key, value in [('MOD_AUDIT_ENABLED', 'false'), ('MOD_API_URL', ''),
                           ('MOD_API_TOKEN', ''), ('MOD_API_URL', 'http://mod.dtcdev.click'),
                           ('MOD_API_URL', 'https://mod.dtcdev.click@other.example')]:
            with self.subTest(key=key, value=value), patch.dict(os.environ, {key: value}):
                with self.assertRaises(RuntimeError):
                    deletion_audit.configuration()

    @patch.object(deletion_audit.requests, 'post')
    def test_retry_preserves_identity_and_requires_committed_response(self, post):
        post.side_effect = [Mock(status_code=503), Mock(status_code=201, json=lambda: {
            'channel': 'C1', 'ts': '123.456', 'committed': True,
        })]
        alert = Mock()
        payload = deletion_audit.persist(self.record, alert)
        self.assertEqual(payload['source'], 'au-tomator')
        self.assertEqual(post.call_args_list[0], post.call_args_list[1])
        self.assertFalse(post.call_args.kwargs['allow_redirects'])
        alert.assert_called_once_with('AUDIT_WRITE_FAILED', 'C1', '123.456', 1)

    @patch.object(deletion_audit.requests, 'post')
    def test_uncommitted_or_wrong_identity_blocks_deletion_after_two_attempts(self, post):
        for result in ({'committed': False}, {'committed': True, 'channel': 'WRONG', 'ts': '123.456'}):
            post.return_value = Mock(status_code=200, json=lambda: result)
            alert = Mock()
            with self.assertRaises(RuntimeError):
                deletion_audit.persist(self.record, alert)
            self.assertEqual(alert.call_count, 2)
            self.assertEqual(alert.call_args.args[-1], 2)

    @patch.object(deletion_audit.requests, 'post')
    def test_pending_receipt_is_durably_logged_and_alerted(self, post):
        post.return_value = Mock(status_code=503)
        payload = {**self.record, 'deleted_at': self.record['timestamp'], 'source': 'au-tomator'}
        alert = Mock()
        with patch.object(deletion_audit.logger, 'info') as log:
            deletion_audit.receipt(payload, alert)
        self.assertIn('AUDIT_DELETE_RECEIPT', log.call_args.args[0])
        self.assertNotIn('example', log.call_args.args[0])
        self.assertEqual(alert.call_count, 2)

    @patch.object(slack, 'get_message_content')
    @patch.object(deletion_audit.requests, 'post')
    def test_committed_write_delete_then_receipt_in_order(self, post, get_message):
        get_message.return_value = {**self.record}
        post.side_effect = [
            Mock(status_code=201, json=lambda: {'committed': True, 'channel': 'C1', 'ts': '123.456'}),
            Mock(json=lambda: {'ok': True}),
            Mock(status_code=201),
        ]
        slack.remove_message('C1', '123.456')
        self.assertEqual([call.args[0] for call in post.call_args_list], [
            'https://mod.dtcdev.click/api/v1/deleted-messages',
            'https://slack.com/api/chat.delete',
            'https://mod.dtcdev.click/api/v1/delete-receipts',
        ])

    @patch.object(slack, 'alert_deletion_audit')
    @patch.object(slack, 'get_message_content')
    @patch.object(deletion_audit.requests, 'post')
    def test_failed_writes_never_call_chat_delete(self, post, get_message, alert):
        get_message.return_value = {**self.record}
        post.side_effect = deletion_audit.requests.Timeout()
        with self.assertRaises(RuntimeError):
            slack.remove_message('C1', '123.456')
        self.assertEqual(post.call_count, 2)
        self.assertTrue(all('/deleted-messages' in call.args[0] for call in post.call_args_list))
        self.assertEqual(alert.call_count, 2)

    def test_deploy_guard_rejects_missing_and_disabled_without_leaking_secrets(self):
        script = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'check_audit_config.py')
        env = {**os.environ, 'PYTHONPATH': os.path.join(os.path.dirname(__file__), '..', 'src')}
        for config in ({}, {'MOD_AUDIT_ENABLED': 'false', 'MOD_API_URL': 'https://mod.dtcdev.click',
                            'MOD_API_TOKEN': 'secret-must-not-appear'}):
            result = subprocess.run([sys.executable, script], input=json.dumps(config),
                                    text=True, capture_output=True, env=env)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('secret-must-not-appear', result.stdout + result.stderr)

    def test_deploy_merge_preserves_existing_environment(self):
        script = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'check_audit_config.py')
        env = {**os.environ, 'PYTHONPATH': os.path.join(os.path.dirname(__file__), '..', 'src')}
        result = subprocess.run([sys.executable, script, '--merge'], input='{"SLACK_TOKEN":"existing"}',
                                text=True, capture_output=True, env=env)
        self.assertEqual(result.returncode, 0)
        merged = json.loads(result.stdout)['Variables']
        self.assertEqual(merged['SLACK_TOKEN'], 'existing')
        self.assertEqual(merged['MOD_AUDIT_ENABLED'], 'true')
