import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault('FAKE_DELETE', '1')
os.environ.setdefault('AUDIT_ENABLED', '0')
os.environ.setdefault('SPAM_TRACKER_ENABLED', '0')
src_dir = os.path.join(os.path.dirname(__file__), '..', 'src')
os.environ['CONFIG_FILE'] = os.path.join(src_dir, 'config.yaml')
sys.path.insert(0, src_dir)

import spam  # noqa: E402


CONFIG = {
    'admins': ['UADMIN'],
    'spam_tracker': {
        'enabled': True,
        'quiet_seconds': 180,
        'min_channels': 2,
        'min_chars': 40,
        'similarity': 0.88,
    },
}

SPAM_TEXT = (
    'Get certified in data engineering today, limited offer, '
    'click https://spam.example/join now!!!'
)


def _event(channel, ts, text=SPAM_TEXT, user='U_SPAMMER'):
    return {
        'type': 'message',
        'user': user,
        'channel': channel,
        'ts': ts,
        'text': text,
    }


class MemoryStore:
    def __init__(self):
        self.items = {}

    def load_sessions(self, user_id):
        prefix = f'USER#{user_id}'
        return [v for k, v in self.items.items() if k[0] == prefix]

    def load_session(self, user_id, fp):
        return self.items.get((f'USER#{user_id}', f'FP#{fp}'))

    def save_session(self, item):
        self.items[(item['pk'], item['sk'])] = dict(item)

    def delete_session(self, user_id, fp):
        self.items.pop((f'USER#{user_id}', f'FP#{fp}'), None)

    def list_ready_sessions(self, cutoff):
        return [
            v for v in self.items.values()
            if v.get('gsi1pk') == 'ready' and int(v.get('gsi1sk') or 0) <= cutoff
        ]

    def hooks(self):
        return {
            'load_sessions': self.load_sessions,
            'save_session': self.save_session,
            'load_session': self.load_session,
            'delete_session': self.delete_session,
            'list_ready_sessions': self.list_ready_sessions,
        }


class TestSimilarity(unittest.TestCase):
    def test_normalize_collapses_slack_markup(self):
        raw = 'Hello <@U123> see <https://x.example|x.example>  NOW'
        self.assertEqual(spam.normalize_text(raw), 'hello see https://x.example now')

    def test_same_text_is_similar(self):
        self.assertTrue(spam.is_similar(SPAM_TEXT, SPAM_TEXT.upper()))

    def test_small_edit_is_similar(self):
        other = SPAM_TEXT.replace('today', 'today!')
        self.assertTrue(spam.is_similar(SPAM_TEXT, other, 0.88))

    def test_unrelated_is_not_similar(self):
        self.assertFalse(spam.is_similar(SPAM_TEXT, 'anyone know the homework deadline?'))


class TestShouldIngest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'SPAM_TRACKER_ENABLED': '1'})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_skips_short_and_admin_and_bots(self):
        self.assertFalse(spam.should_ingest(
            _event('C1', '1.0', text='hi'), CONFIG,
        ))
        self.assertFalse(spam.should_ingest(
            _event('C1', '1.0', user='UADMIN'), CONFIG,
        ))
        bot = _event('C1', '1.0')
        bot['bot_id'] = 'B1'
        self.assertFalse(spam.should_ingest(bot, CONFIG))
        changed = _event('C1', '1.0')
        changed['subtype'] = 'message_changed'
        self.assertFalse(spam.should_ingest(changed, CONFIG))

    def test_accepts_long_user_message(self):
        self.assertTrue(spam.should_ingest(_event('C1', '1.0'), CONFIG))


class TestIngest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'SPAM_TRACKER_ENABLED': '1'})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_one_channel_stays_off_ready_index(self):
        store = MemoryStore()
        item = spam.ingest_message(
            _event('C1', '1.0'), CONFIG, now=1000, store=store.hooks(),
        )
        self.assertEqual(item['channel_count'], 1)
        self.assertNotIn('gsi1pk', item)
        self.assertEqual(store.list_ready_sessions(1000), [])

    def test_second_channel_marks_ready_with_last_seen(self):
        store = MemoryStore()
        hooks = store.hooks()
        spam.ingest_message(_event('C1', '1.0'), CONFIG, now=1000, store=hooks)
        item = spam.ingest_message(
            _event('C2', '2.0'), CONFIG, now=1010, store=hooks,
        )
        self.assertEqual(item['channel_count'], 2)
        self.assertEqual(item['gsi1pk'], 'ready')
        self.assertEqual(item['gsi1sk'], 1010)
        self.assertEqual(store.list_ready_sessions(1009), [])
        self.assertEqual(len(store.list_ready_sessions(1010)), 1)

    def test_later_copy_moves_last_seen(self):
        store = MemoryStore()
        hooks = store.hooks()
        spam.ingest_message(_event('C1', '1.0'), CONFIG, now=1000, store=hooks)
        spam.ingest_message(_event('C2', '2.0'), CONFIG, now=1010, store=hooks)
        item = spam.ingest_message(
            _event('C3', '3.0'), CONFIG, now=1020, store=hooks,
        )
        self.assertEqual(item['gsi1sk'], 1020)
        self.assertEqual(item['channel_count'], 3)
        self.assertEqual(store.list_ready_sessions(1010), [])
        self.assertEqual(len(store.list_ready_sessions(1020)), 1)

    def test_near_duplicate_joins_same_session(self):
        store = MemoryStore()
        hooks = store.hooks()
        spam.ingest_message(_event('C1', '1.0'), CONFIG, now=1000, store=hooks)
        variant = SPAM_TEXT.replace('today', 'today!')
        item = spam.ingest_message(
            _event('C2', '2.0', text=variant), CONFIG, now=1010, store=hooks,
        )
        self.assertEqual(len(store.items), 1)
        self.assertEqual(len(item['messages']), 2)
