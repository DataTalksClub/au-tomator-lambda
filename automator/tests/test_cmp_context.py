import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import cmp_context
import slack


def state():
    url = 'https://courses.datatalks.club/ml-zoomcamp-2026/'
    return {
        'schema_version': 1, 'fetched_at': '2026-11-12T12:00:00Z',
        'course': dict(slug='ml-zoomcamp-2026', title='ML Zoomcamp 2026', source_url=url,
                       starts_at=None, start_date=None, end_date=None, finished=False),
        'homeworks': [],
        'projects': [dict(slug='project-1', title='Project 1', state='PEER_REVIEWING',
                          starts_at=None, submission_due_date='2026-11-10T23:59:00Z',
                          peer_review_due_date='2026-11-17T23:59:00Z',
                          peer_review_open=True, peer_review_opens_at=None,
                          assignments_created=True, source_url=url)],
        'student': {'mapped': True, 'projects': [
            {'slug': 'project-1', 'assigned_count': 3, 'pending_count': 2}]},
    }


class TestCMPContext(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            'CMP_CONTEXT_ENABLED': '1', 'CMP_BOT_READ_TOKEN': 'read-only-test',
            'CMP_SLACK_TEAM_ID': 'T123',
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.get = patch('cmp_context.requests.get').start()
        self.addCleanup(patch.stopall)
        self.response = self.get.return_value.__enter__.return_value
        self.response.status_code = 200
        self.set_state(state())
        self.payload = {'course': 'machine-learning-zoomcamp', 'scope': 'course',
                        'question': 'Were peer review items assigned?', 'user': 'U123'}
        self.config = {'admins': ['UADMIN'], 'cmp': {'courses': {
            'machine-learning-zoomcamp': 'ml-zoomcamp-2026'}}}
        self.slack = MagicMock()

    def set_state(self, value):
        self.response.iter_content.return_value = [json.dumps(value).encode()]

    def test_get_only_exact_identity_and_private_separation(self):
        payload, counts = cmp_context.enrich(self.payload, self.config, self.slack, 'U123')
        request = self.get.call_args
        self.assertEqual(request.args[0], 'https://courses.datatalks.club/api/bot/courses/ml-zoomcamp-2026/state/')
        self.assertEqual(request.kwargs['params'], {'slack_user_id': 'U123', 'slack_team_id': 'T123'})
        self.assertEqual(request.kwargs['timeout'], (2, 5))
        self.assertFalse(request.kwargs['allow_redirects'])
        self.assertNotIn('student', payload['course_state'])
        self.assertNotIn('assigned_count', json.dumps(payload))
        self.assertEqual(counts, ['Project 1: 3 assigned (2 pending).'])
        self.assertNotIn('course_state', self.payload)

    def test_unexpected_private_fields_stripped(self):
        value = state()
        value['projects'][0]['student_email'] = 'private@example.com'
        value['course']['users'] = ['private']
        self.set_state(value)
        public, _ = cmp_context.fetch_state('ml-zoomcamp-2026', 'U123')
        self.assertNotIn('private', json.dumps(public))

    def test_reaction_does_not_resolve_reactor_identity(self):
        payload, counts = cmp_context.enrich(self.payload, self.config, self.slack)
        self.assertEqual(self.get.call_args.kwargs['params'], {})
        self.assertIsNone(counts)
        self.assertIn('course_state', payload)

    def test_student_counts_only_ephemeral_to_asker(self):
        payload, counts = cmp_context.enrich(self.payload, self.config, self.slack, 'U123')
        cmp_context.send_student_counts(self.slack, 'C123', '123.1', 'U123', payload, counts, ['UADMIN'])
        args = self.slack.post_ephemeral.call_args.args
        self.assertEqual(args[:3], ('C123', 'U123', '123.1'))
        self.assertIn('3 assigned', args[3])
        self.slack.post_message_to_thread.assert_not_called()
        self.slack.post_private_message.assert_not_called()

    def test_unmapped_student_gets_no_counts(self):
        value = state()
        value['student'] = {'mapped': False}
        self.set_state(value)
        _, private = cmp_context.enrich(self.payload, self.config, self.slack, 'U123')
        self.assertIsNone(private)

    def test_malformed_and_failure_cases_alert_and_fallback(self):
        cases = []
        for path, bad in [('schema_version', 99), ('projects', 'bad')]:
            value = state()
            value[path] = bad
            cases.append(value)
        value = state()
        value['course']['slug'] = 'ml-2025'
        cases.append(value)
        value = state()
        value['projects'][0]['source_url'] = 'https://evil.example/'
        cases.append(value)
        value = state()
        value['student']['projects'][0]['assigned_count'] = True
        cases.append(value)
        for value in cases:
            with self.subTest(value=value):
                self.set_state(value)
                self.slack.reset_mock()
                payload, counts = cmp_context.enrich(self.payload, self.config, self.slack, 'U123')
                self.assertEqual(payload, self.payload)
                self.assertIsNone(counts)
                self.slack.post_private_message.assert_called_once()
                self.assertIn('CMP_CONTEXT_FAILED', self.slack.post_private_message.call_args.args[1])

    def test_timeout_is_loud_and_returns_original_payload(self):
        self.get.side_effect = cmp_context.requests.Timeout('secret must not be logged')
        with patch.object(cmp_context.logger, 'error') as log:
            payload, counts = cmp_context.enrich(self.payload, self.config, self.slack)
        self.assertEqual(payload, self.payload)
        self.assertIsNone(counts)
        self.assertNotIn('secret', str(log.call_args_list))
        self.slack.post_private_message.assert_called_once()

    def test_disabled_and_noncourse_requests_do_not_fetch(self):
        with patch.dict(os.environ, {'CMP_CONTEXT_ENABLED': '0'}):
            self.assertEqual(cmp_context.enrich(self.payload, self.config, self.slack), (self.payload, None))
        self.assertEqual(cmp_context.enrich({'scope': 'docs'}, self.config, self.slack), ({'scope': 'docs'}, None))
        self.get.assert_not_called()

    def test_context_arrives_before_llm_and_failure_still_answers(self):
        import importlib.util
        src = Path(__file__).resolve().parents[1] / 'src'
        with patch.dict(os.environ, {'CONFIG_FILE': str(src / 'config.yaml')}):
            spec = importlib.util.spec_from_file_location('cmp_test_lambda', src / 'lambda_function.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        with patch.object(module, 'call_faq_assistant', return_value={'answer': 'Peer review is open.'}) as llm, patch.object(module, 'slack', self.slack):
            self.slack.github_to_slack_markdown.side_effect = lambda s: s
            module.post_faq_assistant_answer('C123', '123.1', self.payload, student_user='U123')
            self.assertIn('course_state', llm.call_args.args[0])
            self.assertNotIn('student', llm.call_args.args[0]['course_state'])
            self.slack.post_message_to_thread.assert_called_once_with('C123', '123.1', 'Peer review is open.')
            self.slack.reset_mock()
            self.get.side_effect = cmp_context.requests.Timeout()
            module.post_faq_assistant_answer('C123', '123.1', self.payload, student_user='U123')
            self.assertNotIn('course_state', llm.call_args.args[0])
            self.slack.post_message_to_thread.assert_called_once()
            self.slack.post_private_message.assert_called_once()

    def test_oversized_and_redirect_responses_rejected(self):
        self.response.iter_content.return_value = [b'x' * 65537]
        with self.assertRaises(ValueError):
            cmp_context.fetch_state('ml-zoomcamp-2026')
        self.response.status_code = 302
        with self.assertRaises(ValueError):
            cmp_context.fetch_state('ml-zoomcamp-2026')

    def test_missing_token_alerts_instead_of_silent_disable(self):
        with patch.dict(os.environ, {'CMP_BOT_READ_TOKEN': ''}):
            payload, _ = cmp_context.enrich(self.payload, self.config, self.slack)
        self.assertEqual(payload, self.payload)
        self.get.assert_not_called()
        self.slack.post_private_message.assert_called_once()

    def test_unknown_course_alerts(self):
        cmp_context.enrich(self.payload, {'admins': ['UADMIN']}, self.slack)
        self.slack.post_private_message.assert_called_once()
        self.get.assert_not_called()

    def test_ephemeral_failure_never_posts_counts_publicly(self):
        payload, counts = cmp_context.enrich(self.payload, self.config, self.slack, 'U123')
        self.slack.post_ephemeral.side_effect = RuntimeError('failed')
        cmp_context.send_student_counts(self.slack, 'C123', '123.1', 'U123', payload, counts, ['UADMIN'])
        self.slack.post_message_to_thread.assert_not_called()
        self.assertNotIn('3 assigned', str(self.slack.post_private_message.call_args))

    @patch('slack.requests.post')
    def test_slack_ephemeral_is_bounded_and_checks_delivery(self, post):
        post.return_value.json.return_value = {'ok': True}
        slack.post_ephemeral('C123', 'U123', '123.1', '3 assigned')
        self.assertEqual(post.call_args.args[0], 'https://slack.com/api/chat.postEphemeral')
        self.assertEqual(post.call_args.kwargs['json']['user'], 'U123')
        self.assertEqual(post.call_args.kwargs['timeout'], (2, 5))
        post.return_value.json.return_value = {'ok': False, 'error': 'user_not_in_channel'}
        with self.assertRaises(RuntimeError):
            slack.post_ephemeral('C123', 'U123', '123.1', '3 assigned')
