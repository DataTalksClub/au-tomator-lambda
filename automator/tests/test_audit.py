import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault('FAKE_DELETE', '1')
os.environ['AUDIT_ENABLED'] = '0'
os.environ['SPAM_TRACKER_ENABLED'] = '0'
src_dir = os.path.join(os.path.dirname(__file__), '..', 'src')
sys.path.insert(0, src_dir)

import audit  # noqa: E402


class TestBuildAuditRecord(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 4, 8, 12, 30, 0, tzinfo=timezone.utc)
        self.event = {
            'user': 'UMOD',
            'reaction': 'ban-user',
            'event_ts': '1775646600.000001',
            'item': {'channel': 'C_AAA', 'ts': '1775646500.000100'},
            'item_user': 'U_SPAMMER',
        }

    def test_keys_and_trigger(self):
        record = audit.build_audit_record(
            self.event,
            'BAN_USER',
            [{
                'channel': 'C_AAA',
                'ts': '1775646500.000100',
                'user': 'U_SPAMMER',
                'text': 'buy followers cheap',
                'kind': 'parent',
                'ok': True,
            }],
            target_user_id='U_SPAMMER',
            channel_name='course-ml-zoomcamp',
            extra={'lookback_hours': 24},
            now=self.now,
        )

        self.assertEqual(record['triggered_by'], 'UMOD')
        self.assertEqual(record['reaction'], 'ban-user')
        self.assertEqual(record['action_type'], 'BAN_USER')
        self.assertEqual(record['target_user_id'], 'U_SPAMMER')
        self.assertEqual(record['channel_name'], 'course-ml-zoomcamp')
        self.assertEqual(record['deleted_messages'][0]['text'], 'buy followers cheap')
        self.assertEqual(record['pk'], 'USER#U_SPAMMER')
        self.assertTrue(record['sk'].startswith('2026-04-08T12:30:00Z#'))
        self.assertEqual(record['gsi1pk'], 'DATE#2026-04-08')
        self.assertEqual(record['expires_at'], int(self.now.timestamp()) + 90 * 86400)
        self.assertEqual(
            record['action_id'],
            'C_AAA:1775646500.000100:ban-user:1775646600.000001',
        )

    def test_clips_long_message_text(self):
        record = audit.build_audit_record(
            self.event,
            'DELETE_MESSAGE',
            [{'channel': 'C_AAA', 'ts': '1', 'text': 'x' * 9000, 'ok': True}],
            now=self.now,
        )
        self.assertEqual(len(record['deleted_messages'][0]['text']), 4001)
        self.assertTrue(record['deleted_messages'][0]['text'].endswith('…'))

    def test_unknown_user_pk_when_target_missing(self):
        record = audit.build_audit_record(
            self.event, 'DELETE_MESSAGE', [], now=self.now,
        )
        self.assertEqual(record['pk'], 'USER#unknown')

    def test_s3_keys_include_date_and_user_prefixes(self):
        record = audit.build_audit_record(
            self.event,
            'BAN_USER',
            [],
            target_user_id='U_SPAMMER',
            now=self.now,
        )
        keys = audit.s3_keys(record)
        self.assertEqual(
            keys,
            [
                'by-date/2026/04/08/C_AAA:1775646500.000100:ban-user:1775646600.000001.json',
                'by-user/U_SPAMMER/2026/04/08/C_AAA:1775646500.000100:ban-user:1775646600.000001.json',
            ],
        )

    def test_drops_none_fields(self):
        record = audit.build_audit_record(
            {'item': {}}, 'DELETE_MESSAGE', [], now=self.now,
        )
        self.assertNotIn('triggered_by', record)
        self.assertNotIn('target_user_id', record)


class TestRecordDeleteAction(unittest.TestCase):
    def test_skips_aws_when_disabled(self):
        event = {
            'user': 'UMOD',
            'reaction': 'delete',
            'item': {'channel': 'C1', 'ts': '1.0'},
        }
        with patch.dict(os.environ, {'AUDIT_ENABLED': '0'}), \
             patch('audit._put_dynamo') as put_d, \
             patch('audit._put_s3') as put_s:
            record = audit.record_delete_action(
                event, 'DELETE_MESSAGE',
                [{'channel': 'C1', 'ts': '1.0', 'text': 'hi', 'ok': True}],
                target_user_id='U1',
            )
        put_d.assert_not_called()
        put_s.assert_not_called()
        self.assertEqual(record['action_type'], 'DELETE_MESSAGE')

    def test_writes_dynamo_and_s3_when_enabled(self):
        event = {
            'user': 'UMOD',
            'reaction': 'delete',
            'item': {'channel': 'C1', 'ts': '1.0'},
        }
        with patch.dict(os.environ, {'AUDIT_ENABLED': '1'}), \
             patch('audit._put_dynamo') as put_d, \
             patch('audit._put_s3') as put_s:
            record = audit.record_delete_action(
                event, 'DELETE_MESSAGE',
                [{'channel': 'C1', 'ts': '1.0', 'text': 'hi', 'ok': True}],
                target_user_id='U1',
            )
        put_d.assert_called_once()
        self.assertEqual(put_d.call_args.args[0]['pk'], 'USER#U1')
        self.assertEqual(put_s.call_count, 2)
        s3_keys = [c.args[0] for c in put_s.call_args_list]
        self.assertTrue(any(k.startswith('by-date/') for k in s3_keys))
        self.assertTrue(any(k.startswith('by-user/U1/') for k in s3_keys))
        self.assertEqual(record['triggered_by'], 'UMOD')

    def test_aws_errors_do_not_raise(self):
        event = {
            'user': 'UMOD',
            'reaction': 'delete',
            'item': {'channel': 'C1', 'ts': '1.0'},
        }
        with patch.dict(os.environ, {'AUDIT_ENABLED': '1'}), \
             patch('audit._put_dynamo', side_effect=RuntimeError('no table')), \
             patch('audit._put_s3', side_effect=RuntimeError('no bucket')):
            record = audit.record_delete_action(
                event, 'DELETE_MESSAGE',
                [{'channel': 'C1', 'ts': '1.0', 'text': 'hi', 'ok': True}],
            )
        self.assertIsNotNone(record)
