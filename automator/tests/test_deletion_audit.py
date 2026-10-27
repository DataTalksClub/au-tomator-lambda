import contextlib
import io
import json
import os
import sys
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import slack


class TestDeletionAudit(unittest.TestCase):
    def setUp(self):
        self.message = {
            'ts': '123.456', 'thread_ts': '123.000', 'user': 'U_AUTHOR',
            'text': 'full text\nwith newline',
            'files': [{'id': 'F1', 'name': 'attachment.pdf'}],
            'blocks': [{'type': 'section'}],
        }

    @patch.object(slack.requests, 'post')
    @patch.object(slack, 'get_message_content')
    def test_full_json_record_precedes_delete(self, get_message, post):
        get_message.return_value = self.message
        output = io.StringIO()
        def delete(*args, **kwargs):
            record = json.loads(output.getvalue().splitlines()[0])
            self.assertEqual(record['tag'], 'AUDIT_DELETED_MESSAGE')
            self.assertEqual(record['message'], self.message)
            self.assertEqual(record['files'], self.message['files'])
            self.assertEqual(record['reacting_admin'], 'U_ADMIN')
            self.assertEqual(record['reaction'], 'delete')
            self.assertEqual(record['channel'], 'C_TEST')
            self.assertEqual(record['thread_ts'], '123.000')
            self.assertTrue(record['timestamp'])
            return Mock(json=lambda: {'ok': True})
        post.side_effect = delete
        token = slack.deletion_context.set({'user': 'U_ADMIN', 'reaction': 'delete'})
        try:
            with contextlib.redirect_stdout(output):
                slack.remove_message('C_TEST', '123.456')
        finally:
            slack.deletion_context.reset(token)
        post.assert_called_once()

    @patch.object(slack.requests, 'post')
    @patch.object(slack, 'get_message_content')
    def test_missing_full_message_prevents_delete(self, get_message, post):
        for message in (None, {'ts': 'wrong'}):
            get_message.return_value = message
            with self.assertRaises(RuntimeError):
                slack.remove_message('C_TEST', '123.456')
        post.assert_not_called()

    @patch.object(slack.requests, 'post')
    @patch.object(slack, 'get_message_content')
    def test_log_failure_prevents_delete(self, get_message, post):
        get_message.return_value = self.message
        with patch.object(slack.logger, 'info', side_effect=OSError('log unavailable')):
            with self.assertRaises(OSError):
                slack.remove_message('C_TEST', '123.456')
        post.assert_not_called()
