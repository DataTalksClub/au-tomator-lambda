"""End-to-end reaction routing tests.

These drive whole events through ``lambda_handler`` / ``process_reaction`` with
``slack`` / ``groqu`` / ``call_faq_assistant`` mocked, and assert that each
reaction produces the right Slack calls — including channel-specific behaviour
(placeholders, FAQ course scope). The message-formatting layer (``util``) is
NOT mocked, so these also exercise real templating.

This replaces the old ``integration/test.py``, which fired reactions at the live
Slack API and asserted nothing.
"""

import os
import sys
import importlib.util
import unittest
from unittest.mock import patch, ANY

# Load the automator lambda_function once, reusing the instance registered by
# test_automator_lambda.py if it ran first (so module-level patches target the
# same object). Bootstrap it ourselves when run in isolation.
MODNAME = 'automator_lambda_function'
if MODNAME in sys.modules:
    lambda_function = sys.modules[MODNAME]
else:
    os.environ['FAKE_DELETE'] = '1'
    src_dir = os.path.join(os.path.dirname(__file__), '..', 'src')
    os.environ['CONFIG_FILE'] = os.path.join(src_dir, 'config.yaml')
    spec = importlib.util.spec_from_file_location(
        MODNAME, os.path.join(src_dir, 'lambda_function.py')
    )
    lambda_function = importlib.util.module_from_spec(spec)
    sys.modules[MODNAME] = lambda_function
    sys.path.insert(0, src_dir)
    spec.loader.exec_module(lambda_function)
    sys.path.pop(0)


# Real channel IDs from config.yaml.
CH_DE = 'C01FABYF2RG'      # course-data-engineering
CH_ML = 'C0288NJ5XSA'      # course-ml-zoomcamp
CH_OTHER = 'C_OTHER'       # not in config -> no course / 'default' placeholder

ASKING_QUESTIONS_URL = (
    'https://datatalks.club/docs/courses/zoomcamp-logistics/asking-questions/'
)
ASKING_FOR_HELP_URL = (
    'https://datatalks.club/docs/general/guidelines/asking-for-help/'
)


def reaction_event(reaction, channel=CH_DE, ts='1700000000.000100', user='UMOD'):
    return {
        'type': 'reaction_added',
        'reaction': reaction,
        'user': user,
        'item': {'channel': channel, 'ts': ts},
    }


def deliver(event):
    """Route an event through the real top-level handler."""
    return lambda_function.lambda_handler({'event': event}, None)


class TestSlackPostRouting(unittest.TestCase):
    """Plain SLACK_POST reactions post the configured message to the thread."""

    @patch('automator_lambda_function.slack')
    def test_plain_slack_post_reactions(self, mock_slack):
        for reaction in ['dont-ask-to-ask-just-ask', 'thread']:
            with self.subTest(reaction=reaction):
                mock_slack.reset_mock()
                deliver(reaction_event(reaction))
                mock_slack.post_message_thread.assert_called_once()
                # No deletion / DM for an informational post.
                mock_slack.remove_message.assert_not_called()
                mock_slack.send_dm.assert_not_called()


class TestPlaceholderSlackPost(unittest.TestCase):
    """no-screenshot is a SLACK_POST with channel-specific link placeholders."""

    @patch('automator_lambda_function.slack')
    def test_no_screenshot_resolves_link_per_channel(self, mock_slack):
        cases = [
            (CH_DE, ASKING_QUESTIONS_URL),
            (CH_OTHER, ASKING_FOR_HELP_URL),
        ]
        for channel, expected_url in cases:
            with self.subTest(channel=channel):
                mock_slack.reset_mock()
                deliver(reaction_event('no-screenshot', channel=channel))
                mock_slack.post_message_thread.assert_called_once()
                posted = mock_slack.post_message_thread.call_args[0][1]
                self.assertIn(expected_url, posted)


class TestBeSpecificRouting(unittest.TestCase):
    """be-specific points course channels to course guidance and others to general guidance."""

    @patch('automator_lambda_function.slack')
    def test_be_specific_resolves_copy_per_channel(self, mock_slack):
        cases = [
            (
                CH_DE,
                ASKING_QUESTIONS_URL,
                'module, lesson, homework, or project step',
            ),
            (
                CH_OTHER,
                ASKING_FOR_HELP_URL,
                'relevant context and environment',
            ),
        ]
        for channel, expected_url, expected_context in cases:
            with self.subTest(channel=channel):
                mock_slack.reset_mock()
                deliver(reaction_event('be-specific', channel=channel))
                mock_slack.post_message_thread.assert_called_once()
                posted = mock_slack.post_message_thread.call_args[0][1]
                self.assertIn(expected_url, posted)
                self.assertIn(expected_context, posted)
                self.assertIn("it's not possible to help effectively", posted)


class TestDeleteMessageRouting(unittest.TestCase):
    """DELETE_MESSAGE reactions DM the author and (would) delete the message."""

    DELETE_REACTIONS = [
        'thread-please', 'shameless-rules', 'jobs-rules',
        'ask-in-course-channel', 'to-welcome', 'delete',
    ]

    @patch('automator_lambda_function.slack')
    def test_delete_reactions_dm_author_and_skip_delete_in_fake_mode(self, mock_slack):
        for reaction in self.DELETE_REACTIONS:
            with self.subTest(reaction=reaction):
                mock_slack.reset_mock()
                mock_slack.get_message_content.return_value = {
                    'user': 'U_AUTHOR',
                    'text': 'a message that broke a rule',
                }
                mock_slack.get_thread_replies.return_value = []

                deliver(reaction_event(reaction))

                mock_slack.send_dm.assert_called_once()
                self.assertEqual(mock_slack.send_dm.call_args[0][0], 'U_AUTHOR')
                # FAKE_DELETE=1 -> never actually deletes.
                mock_slack.remove_message.assert_not_called()

    @patch('automator_lambda_function.slack')
    def test_delete_skips_when_message_has_no_user(self, mock_slack):
        mock_slack.get_message_content.return_value = {'text': 'bot message, no user'}
        deliver(reaction_event('delete'))
        mock_slack.send_dm.assert_not_called()
        mock_slack.remove_message.assert_not_called()


class TestRepostPerChannel(unittest.TestCase):
    """REPOST_TO_THREAD_AND_DELETE reposts the original text per channel."""

    @patch('automator_lambda_function.slack')
    def test_error_log_reposts_original_message(self, mock_slack):
        cases = [
            (CH_DE, ASKING_QUESTIONS_URL),
            (CH_ML, ASKING_QUESTIONS_URL),
            (CH_OTHER, ASKING_FOR_HELP_URL),
        ]
        for channel, expected_url in cases:
            with self.subTest(channel=channel):
                mock_slack.reset_mock()
                mock_slack.get_message_content.return_value = {
                    'user': 'U_AUTHOR',
                    'text': 'here is my error log',
                }
                deliver(reaction_event('error-log-to-thread-please', channel=channel))

                mock_slack.post_message_thread.assert_called_once()
                posted = mock_slack.post_message_thread.call_args[0][1]
                self.assertIn('here is my error log', posted)
                self.assertIn(expected_url, posted)
                mock_slack.remove_message.assert_not_called()  # FAKE_DELETE


class TestFaqPerChannel(unittest.TestCase):
    """faq reaction builds a course/docs payload depending on the channel."""

    @patch('automator_lambda_function.call_faq_assistant')
    @patch('automator_lambda_function.slack')
    def test_faq_payload_scope_per_channel(self, mock_slack, mock_call):
        cases = [
            (CH_DE, 'course', 'data-engineering-zoomcamp'),
            (CH_ML, 'course', 'machine-learning-zoomcamp'),
            (CH_OTHER, 'docs', None),
        ]
        for channel, scope, course in cases:
            with self.subTest(channel=channel):
                mock_slack.reset_mock()
                mock_call.reset_mock()
                mock_slack.get_message.return_value = ('U_ASKER', 'Can I still join?')
                mock_slack.github_to_slack_markdown.side_effect = lambda text: text
                mock_call.return_value = {'answer': 'Yes, you can.'}

                deliver(reaction_event('faq', channel=channel))

                mock_call.assert_called_once()
                payload = mock_call.call_args[0][0]
                self.assertEqual(payload['question'], 'Can I still join?')
                self.assertEqual(payload['scope'], scope)
                if course is None:
                    self.assertNotIn('course', payload)
                else:
                    self.assertEqual(payload['course'], course)
                mock_slack.post_message_to_thread.assert_called_once()


class TestAskAiRouting(unittest.TestCase):
    """ask-ai reaction asks the model and posts the answer to the thread."""

    @patch('automator_lambda_function.groqu')
    @patch('automator_lambda_function.slack')
    def test_ask_ai_posts_model_answer(self, mock_slack, mock_groqu):
        mock_slack.get_message.return_value = ('U_ASKER', 'What is a vector db?')
        mock_slack.github_to_slack_markdown.side_effect = lambda text: text
        mock_groqu.ai_request.return_value = 'A vector database stores embeddings.'

        deliver(reaction_event('ask-ai'))

        mock_groqu.ai_request.assert_called_once()
        mock_slack.post_message_thread.assert_called_once()
        posted = mock_slack.post_message_thread.call_args[0][1]
        self.assertIn('A vector database stores embeddings.', posted)


class TestBanUserRouting(unittest.TestCase):
    """ban-user reaction routes to the cleanup handler and DMs the moderator."""

    @patch('automator_lambda_function.slack')
    def test_ban_user_routes_and_summarizes(self, mock_slack):
        mock_slack.get_message_content.return_value = {
            'user': 'U_SPAMMER', 'text': 'spam',
        }
        mock_slack.get_user_info.return_value = {'name': 'spammer', 'profile': {}}
        mock_slack.search_user_messages.return_value = []
        mock_slack.get_thread_replies.return_value = []

        deliver(reaction_event('ban-user', user='UMOD'))

        mock_slack.get_message_content.assert_called_once()
        # Moderator gets the cleanup summary + an ID-only DM; spammer is not DM'd.
        mock_slack.send_dm_blocks.assert_called_once_with('UMOD', ANY, ANY)
        dm_targets = [c.args[0] for c in mock_slack.send_dm.call_args_list]
        self.assertNotIn('U_SPAMMER', dm_targets)


class TestAppMentionRouting(unittest.TestCase):
    """app_mention events route to the FAQ assistant and answer in-thread."""

    @patch('automator_lambda_function.call_faq_assistant')
    @patch('automator_lambda_function.slack')
    def test_app_mention_answers_in_thread(self, mock_slack, mock_call):
        mock_slack.github_to_slack_markdown.side_effect = lambda text: text
        mock_call.return_value = {'answer': 'Yes, you can still join.'}
        event = {
            'type': 'app_mention',
            'channel': CH_ML,
            'text': '<@UFAQBOT> Can I still join?',
            'ts': '1700000000.000100',
        }

        deliver(event)

        payload = mock_call.call_args[0][0]
        self.assertEqual(payload['scope'], 'course')
        self.assertEqual(payload['course'], 'machine-learning-zoomcamp')
        mock_slack.post_message_to_thread.assert_called_once()


class TestUnknownReaction(unittest.TestCase):
    """A reaction with no config does nothing."""

    @patch('automator_lambda_function.slack')
    def test_unknown_reaction_is_noop(self, mock_slack):
        deliver(reaction_event('not-a-real-reaction'))
        mock_slack.post_message_thread.assert_not_called()
        mock_slack.send_dm.assert_not_called()
        mock_slack.remove_message.assert_not_called()


if __name__ == '__main__':
    unittest.main()
