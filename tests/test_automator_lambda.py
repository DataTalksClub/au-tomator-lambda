import sys
import os
import unittest
from unittest.mock import patch, MagicMock
import importlib.util

# Set environment before importing lambda_function
os.environ['FAKE_DELETE'] = '1'
config_path = os.path.join(os.path.dirname(__file__), '..', 'automator', 'config.yaml')
os.environ['CONFIG_FILE'] = config_path

# Load the automator lambda_function directly without adding to path
automator_lambda_path = os.path.join(os.path.dirname(__file__), '..', 'automator', 'lambda_function.py')
spec = importlib.util.spec_from_file_location("automator_lambda_function", automator_lambda_path)
lambda_function = importlib.util.module_from_spec(spec)

# Register in sys.modules so patching works
# This is needed because we load the module dynamically to avoid conflicts with moderator tests
sys.modules['automator_lambda_function'] = lambda_function

# Add automator to sys.path temporarily for imports within lambda_function
automator_dir = os.path.join(os.path.dirname(__file__), '..', 'automator')
sys.path.insert(0, automator_dir)
spec.loader.exec_module(lambda_function)
sys.path.pop(0)


class TestDeleteMessage(unittest.TestCase):
    """Test DELETE_MESSAGE handler with and without thread support"""
    
    @patch('automator_lambda_function.slack')
    @patch('automator_lambda_function.util')
    def test_delete_message_without_threads(self, mock_util, mock_slack):
        """Test DELETE_MESSAGE without thread_message config"""
        # Setup mocks
        mock_slack.get_message_content.return_value = {
            'user': 'U123456',
            'text': 'This is a test message'
        }
        mock_util.format_message.return_value = "DM message to user"
        
        # Create event
        event = {
            'item': {
                'channel': 'C123456',
                'ts': '1234567890.123456'
            },
            'reaction': 'shameless-rules'
        }
        
        # Create reaction config without thread_message
        reaction_config = {
            'message': 'Hi <@{user}>! Your message was removed.',
            'type': 'DELETE_MESSAGE'
        }
        
        # Execute
        lambda_function.handle_delete_message(event, reaction_config)
        
        # Verify
        mock_slack.get_message_content.assert_called_once_with('C123456', '1234567890.123456')
        mock_slack.send_dm.assert_called_once_with('U123456', "DM message to user")
        # Should not call get_thread_replies when no thread_message
        mock_slack.get_thread_replies.assert_not_called()
    
    @patch('automator_lambda_function.slack')
    @patch('automator_lambda_function.util')
    def test_delete_message_with_threads(self, mock_util, mock_slack):
        """Test DELETE_MESSAGE with thread_message config"""
        # Setup mocks
        mock_slack.get_message_content.return_value = {
            'user': 'U_PARENT',
            'text': 'Parent message'
        }
        mock_slack.get_thread_replies.return_value = [
            {'user': 'U_REPLY1', 'ts': '1234567890.123457', 'text': 'Reply 1'},
            {'user': 'U_REPLY2', 'ts': '1234567890.123458', 'text': 'Reply 2'},
        ]
        mock_util.format_message.return_value = "DM message"
        
        # Create event
        event = {
            'item': {
                'channel': 'C123456',
                'ts': '1234567890.123456'
            },
            'reaction': 'delete'
        }
        
        # Create reaction config with thread_message
        reaction_config = {
            'message': 'Hi <@{user}>! Your message was removed.',
            'thread_message': 'Hi <@{user}>! Your reply was removed.',
            'type': 'DELETE_MESSAGE'
        }
        
        # Execute
        lambda_function.handle_delete_message(event, reaction_config)
        
        # Verify
        mock_slack.get_message_content.assert_called_once()
        mock_slack.get_thread_replies.assert_called_once_with('C123456', '1234567890.123456')
        # Should send DMs to parent and 2 replies (3 total)
        assert mock_slack.send_dm.call_count == 3
    
    @patch('automator_lambda_function.slack')
    @patch('automator_lambda_function.util')
    def test_delete_message_no_user(self, mock_util, mock_slack):
        """Test DELETE_MESSAGE handles missing user gracefully"""
        # Setup mocks - message without user (e.g., bot message)
        mock_slack.get_message_content.return_value = {
            'text': 'Bot message without user'
        }
        
        # Create event
        event = {
            'item': {
                'channel': 'C123456',
                'ts': '1234567890.123456'
            },
            'reaction': 'shameless-rules'
        }
        
        # Create reaction config
        reaction_config = {
            'message': 'Hi <@{user}>! Your message was removed.',
            'type': 'DELETE_MESSAGE'
        }
        
        # Execute
        lambda_function.handle_delete_message(event, reaction_config)
        
        # Verify - should not send DM or delete when no user
        mock_slack.send_dm.assert_not_called()
        mock_slack.remove_message.assert_not_called()
    
    @patch('automator_lambda_function.slack')
    @patch('automator_lambda_function.util')
    def test_delete_message_message_not_found(self, mock_util, mock_slack):
        """Test DELETE_MESSAGE handles missing message gracefully"""
        # Setup mocks - get_message_content returns None
        mock_slack.get_message_content.return_value = None
        
        # Create event
        event = {
            'item': {
                'channel': 'C123456',
                'ts': '1234567890.123456'
            },
            'reaction': 'shameless-rules'
        }
        
        # Create reaction config
        reaction_config = {
            'message': 'Hi <@{user}>! Your message was removed.',
            'type': 'DELETE_MESSAGE'
        }
        
        # Execute
        lambda_function.handle_delete_message(event, reaction_config)
        
        # Verify - should not send DM or delete when message not found
        mock_slack.send_dm.assert_not_called()
        mock_slack.remove_message.assert_not_called()
    
    @patch('automator_lambda_function.slack')
    @patch('automator_lambda_function.util')
    def test_delete_message_with_threads_skip_bot_replies(self, mock_util, mock_slack):
        """Test DELETE_MESSAGE skips bot messages in threads"""
        # Setup mocks
        mock_slack.get_message_content.return_value = {
            'user': 'U_PARENT',
            'text': 'Parent message'
        }
        # Mix of user and bot replies
        mock_slack.get_thread_replies.return_value = [
            {'user': 'U_REPLY1', 'ts': '1234567890.123457', 'text': 'Reply 1'},
            {'ts': '1234567890.123458', 'text': 'Bot reply without user'},  # No user field
            {'user': 'U_REPLY2', 'ts': '1234567890.123459', 'text': 'Reply 2'},
        ]
        mock_util.format_message.return_value = "DM message"
        
        # Create event
        event = {
            'item': {
                'channel': 'C123456',
                'ts': '1234567890.123456'
            },
            'reaction': 'delete'
        }
        
        # Create reaction config with thread_message
        reaction_config = {
            'message': 'Hi <@{user}>! Your message was removed.',
            'thread_message': 'Hi <@{user}>! Your reply was removed.',
            'type': 'DELETE_MESSAGE'
        }
        
        # Execute
        lambda_function.handle_delete_message(event, reaction_config)
        
        # Verify - should send DMs to parent and 2 user replies (3 total), skipping bot
        assert mock_slack.send_dm.call_count == 3

    @patch('automator_lambda_function.slack')
    @patch('automator_lambda_function.util')
    def test_delete_message_with_curly_braces_in_user_message(self, mock_util, mock_slack):
        """Test DELETE_MESSAGE handles curly braces in user message (e.g., {POSTGRES_DB})"""
        # Setup mocks - user message contains curly braces like environment variables
        mock_slack.get_message_content.return_value = {
            'user': 'U123456',
            'text': 'How do I set {POSTGRES_DB} in my environment?'
        }
        mock_util.format_message.return_value = "DM message to user"

        # Create event
        event = {
            'item': {
                'channel': 'C123456',
                'ts': '1234567890.123456'
            },
            'reaction': 'ask-in-course-channel'
        }

        # Create reaction config
        reaction_config = {
            'message': 'Hi <@{user}>! Your message: > {user_message} was removed.',
            'type': 'DELETE_MESSAGE'
        }

        # Execute - should not raise KeyError
        lambda_function.handle_delete_message(event, reaction_config)

        # Verify
        mock_slack.send_dm.assert_called_once_with('U123456', "DM message to user")


class TestReactionConfig(unittest.TestCase):
    """Test that reaction configs are properly loaded"""
    
    def test_delete_reaction_has_thread_message(self):
        """Verify that 'delete' reaction has thread_message configured"""
        reaction_config = lambda_function.reaction_configs.get('delete')
        self.assertIsNotNone(reaction_config)
        self.assertEqual(reaction_config['type'], 'DELETE_MESSAGE')
        self.assertIn('thread_message', reaction_config)
    
    def test_shameless_rules_has_thread_message(self):
        """Verify that 'shameless-rules' reaction now has thread_message"""
        reaction_config = lambda_function.reaction_configs.get('shameless-rules')
        self.assertIsNotNone(reaction_config)
        self.assertEqual(reaction_config['type'], 'DELETE_MESSAGE')
        self.assertIn('thread_message', reaction_config)
    
    def test_jobs_rules_has_thread_message(self):
        """Verify that 'jobs-rules' reaction has thread_message"""
        reaction_config = lambda_function.reaction_configs.get('jobs-rules')
        self.assertIsNotNone(reaction_config)
        self.assertEqual(reaction_config['type'], 'DELETE_MESSAGE')
        self.assertIn('thread_message', reaction_config)
    
    def test_ask_in_course_channel_has_thread_message(self):
        """Verify that 'ask-in-course-channel' reaction has thread_message"""
        reaction_config = lambda_function.reaction_configs.get('ask-in-course-channel')
        self.assertIsNotNone(reaction_config)
        self.assertEqual(reaction_config['type'], 'DELETE_MESSAGE')
        self.assertIn('thread_message', reaction_config)
    
    def test_to_welcome_has_thread_message(self):
        """Verify that 'to-welcome' reaction has thread_message"""
        reaction_config = lambda_function.reaction_configs.get('to-welcome')
        self.assertIsNotNone(reaction_config)
        self.assertEqual(reaction_config['type'], 'DELETE_MESSAGE')
        self.assertIn('thread_message', reaction_config)
    
    def test_thread_please_reaction_exists(self):
        """Verify that 'thread-please' reaction is configured"""
        reaction_config = lambda_function.reaction_configs.get('thread-please')
        self.assertIsNotNone(reaction_config)
        self.assertEqual(reaction_config['type'], 'DELETE_MESSAGE')
        self.assertIn('message', reaction_config)
        # Verify the message contains expected text
        message = reaction_config['message']
        self.assertIn('broadcast', message.lower())
        self.assertIn('guidelines', message.lower())
    
    def test_action_handlers_has_delete_message(self):
        """Verify that DELETE_MESSAGE handler is registered"""
        self.assertIn('DELETE_MESSAGE', lambda_function.action_handlers)
        self.assertEqual(
            lambda_function.action_handlers['DELETE_MESSAGE'],
            lambda_function.handle_delete_message
        )
    
    def test_action_handlers_no_delete_with_threads(self):
        """Verify that DELETE_WITH_THREADS handler is removed"""
        self.assertNotIn('DELETE_WITH_THREADS', lambda_function.action_handlers)
    
    def test_action_handlers_has_remove_broadcast(self):
        """Verify that REMOVE_BROADCAST handler is registered"""
        self.assertIn('REMOVE_BROADCAST', lambda_function.action_handlers)
        self.assertEqual(
            lambda_function.action_handlers['REMOVE_BROADCAST'],
            lambda_function.handle_remove_broadcast
        )
    
    def test_thread_reaction_uses_single_handler(self):
        """Verify that 'thread' reaction uses single SLACK_POST handler"""
        reaction_config = lambda_function.reaction_configs.get('thread')
        self.assertIsNotNone(reaction_config)
        self.assertIn('type', reaction_config)
        self.assertEqual(reaction_config['type'], 'SLACK_POST')
        # Should not have 'types' (multiple handlers)
        self.assertNotIn('types', reaction_config)
    
    def test_error_log_to_thread_and_delete_reaction_exists(self):
        """Verify that 'error-log-to-thread-and-delete' reaction is configured"""
        reaction_config = lambda_function.reaction_configs.get('error-log-to-thread-please')
        self.assertIsNotNone(reaction_config)
        self.assertEqual(reaction_config['type'], 'REPOST_TO_THREAD_AND_DELETE')
        self.assertIn('message', reaction_config)
        self.assertIn('placeholders', reaction_config)
        # Verify the message contains expected text
        message = reaction_config['message']
        self.assertIn('Removing the message', message)
        self.assertIn('original message', message.lower())
        self.assertIn('{user_message}', message)
    
    def test_action_handlers_has_repost_to_thread_and_delete(self):
        """Verify that REPOST_TO_THREAD_AND_DELETE handler is registered"""
        self.assertIn('REPOST_TO_THREAD_AND_DELETE', lambda_function.action_handlers)
        self.assertEqual(
            lambda_function.action_handlers['REPOST_TO_THREAD_AND_DELETE'],
            lambda_function.handle_repost_to_thread_and_delete
        )


class TestRemoveBroadcast(unittest.TestCase):
    """Test REMOVE_BROADCAST handler"""
    
    @patch('automator_lambda_function.slack')
    def test_regular_message_not_removed(self, mock_slack):
        """Test that regular messages (not broadcasted) are not removed"""
        # Setup mocks - regular message without thread_ts
        mock_slack.get_message_content.return_value = {
            'user': 'U123456',
            'text': 'Regular message',
            'ts': '1234567890.123456'
        }
        
        # Create event
        event = {
            'item': {
                'channel': 'C123456',
                'ts': '1234567890.123456'
            },
            'reaction': 'thread'
        }
        
        # Create reaction config
        reaction_config = {
            'types': ['REMOVE_BROADCAST', 'SLACK_POST'],
            'message': 'Please use threads'
        }
        
        # Execute
        lambda_function.handle_remove_broadcast(event, reaction_config)
        
        # Verify - should not delete regular messages
        mock_slack.remove_message.assert_not_called()
    
    @patch('automator_lambda_function.slack')
    def test_broadcasted_reply_removed(self, mock_slack):
        """Test that broadcasted thread replies are removed from channel"""
        # Setup mocks - broadcasted thread reply (thread_ts != ts)
        mock_slack.get_message_content.return_value = {
            'user': 'U123456',
            'text': 'Reply sent to channel',
            'ts': '1234567890.123457',
            'thread_ts': '1234567890.123456'  # Different from ts
        }
        
        # Create event
        event = {
            'item': {
                'channel': 'C123456',
                'ts': '1234567890.123457'
            },
            'reaction': 'thread'
        }
        
        # Create reaction config
        reaction_config = {
            'types': ['REMOVE_BROADCAST', 'SLACK_POST'],
            'message': 'Please use threads'
        }
        
        # Execute
        lambda_function.handle_remove_broadcast(event, reaction_config)
        
        # Verify - in FAKE_DELETE mode, remove_message is not called but logged
        # The message would be deleted in production (when FAKE_DELETE=0)
        mock_slack.remove_message.assert_not_called()  # Because FAKE_DELETE=1
    
    @patch('automator_lambda_function.slack')
    def test_parent_message_not_removed(self, mock_slack):
        """Test that parent messages (thread_ts == ts) are not removed"""
        # Setup mocks - parent message where thread_ts == ts
        mock_slack.get_message_content.return_value = {
            'user': 'U123456',
            'text': 'Parent message',
            'ts': '1234567890.123456',
            'thread_ts': '1234567890.123456'  # Same as ts
        }
        
        # Create event
        event = {
            'item': {
                'channel': 'C123456',
                'ts': '1234567890.123456'
            },
            'reaction': 'thread'
        }
        
        # Create reaction config
        reaction_config = {
            'types': ['REMOVE_BROADCAST', 'SLACK_POST'],
            'message': 'Please use threads'
        }
        
        # Execute
        lambda_function.handle_remove_broadcast(event, reaction_config)
        
        # Verify - should not delete parent messages
        mock_slack.remove_message.assert_not_called()
    
    @patch('automator_lambda_function.slack')
    def test_message_not_found(self, mock_slack):
        """Test handler gracefully handles missing message"""
        # Setup mocks - message not found
        mock_slack.get_message_content.return_value = None
        
        # Create event
        event = {
            'item': {
                'channel': 'C123456',
                'ts': '1234567890.123456'
            },
            'reaction': 'thread'
        }
        
        # Create reaction config
        reaction_config = {
            'types': ['REMOVE_BROADCAST', 'SLACK_POST'],
            'message': 'Please use threads'
        }
        
        # Execute
        lambda_function.handle_remove_broadcast(event, reaction_config)
        
        # Verify - should not delete when message not found
        mock_slack.remove_message.assert_not_called()


class TestMultipleHandlers(unittest.TestCase):
    """Test that multiple handlers can be executed for one reaction"""
    
    @patch('automator_lambda_function.slack')
    @patch('automator_lambda_function.util')
    def test_thread_reaction_executes_single_handler(self, mock_util, mock_slack):
        """Test that thread reaction executes only SLACK_POST"""
        # Setup mocks
        mock_util.format_message.return_value = None
        
        # Create event
        event = {
            'item': {
                'channel': 'C123456',
                'ts': '1234567890.123457'
            },
            'reaction': 'thread'
        }
        
        # Create body
        body = {
            'event': event
        }
        
        # Execute the full reaction processing
        lambda_function.process_reaction(body, event)
        
        # Verify only SLACK_POST handler was called:
        # SLACK_POST called post_message_thread
        mock_slack.post_message_thread.assert_called_once()
        # REMOVE_BROADCAST should NOT be called (no get_message_content for removal)
        mock_slack.remove_message.assert_not_called()


class TestChannelConfig(unittest.TestCase):
    """Test that channel configurations are correct"""
    
    def test_ai_dev_tools_channel_exists(self):
        """Verify that course-ai-dev-tools-zoomcamp channel is configured"""
        channel_name = lambda_function.get_channel_name('C09HWT76L95')
        self.assertEqual(channel_name, 'course-ai-dev-tools-zoomcamp')
    
    def test_all_expected_channels(self):
        """Verify all expected channels are configured"""
        expected_channels = {
            'C02R98X7DS9': 'course-mlops-zoomcamp',
            'C01FABYF2RG': 'course-data-engineering',
            'C0288NJ5XSA': 'course-ml-zoomcamp',
            'C06TEGTGM3J': 'course-llm-zoomcamp',
            'C09HWT76L95': 'course-ai-dev-tools-zoomcamp',
            'C06L1RTF10F': 'course-stock-markets-analytics-zoomcamp',
        }
        
        for channel_id, expected_name in expected_channels.items():
            channel_name = lambda_function.get_channel_name(channel_id)
            self.assertEqual(
                channel_name, 
                expected_name,
                f"Channel {channel_id} should be {expected_name}"
            )


class TestAskAi(unittest.TestCase):
    """Test ASK_AI handler"""

    @patch('automator_lambda_function.groqu')
    @patch('automator_lambda_function.slack')
    def test_ask_ai_with_curly_braces_in_user_message(self, mock_slack, mock_groqu):
        """Test ASK_AI handles curly braces in user message (e.g., {POSTGRES_DB})"""
        # Setup mocks - user message contains curly braces like environment variables
        mock_slack.get_message.return_value = ('U123456', 'How do I set {POSTGRES_DB} in my environment?')
        mock_groqu.ai_request.return_value = 'You can set POSTGRES_DB in your docker-compose.yml file.'
        mock_slack.github_to_slack_markdown.return_value = 'You can set POSTGRES_DB in your docker-compose.yml file.'

        # Create event
        event = {
            'item': {
                'channel': 'C123456',
                'ts': '1234567890.123456'
            },
            'reaction': 'ask-ai'
        }

        # Create reaction config
        reaction_config = {
            'type': 'ASK_AI',
            'model': 'meta-llama/llama-4-scout-17b-16e-instruct',
            'prompt_template': 'Answer: {user_message}',
            'answer_template': 'Hi <@{user}>! AI says: {ai_response}'
        }

        # Execute - should not raise KeyError
        lambda_function.handle_ask_ai(event, reaction_config)

        # Verify groqu was called with escaped curly braces
        mock_groqu.ai_request.assert_called_once()
        call_args = mock_groqu.ai_request.call_args[0]
        # The prompt should contain {{POSTGRES_DB}} instead of {POSTGRES_DB}
        self.assertIn('{{POSTGRES_DB}}', call_args[0])

        # Verify message was posted to thread
        mock_slack.post_message_thread.assert_called_once()


class TestRepostToThreadAndDelete(unittest.TestCase):
    """Test REPOST_TO_THREAD_AND_DELETE handler"""
    
    @patch('automator_lambda_function.slack')
    def test_repost_with_placeholders(self, mock_slack):
        """Test REPOST_TO_THREAD_AND_DELETE with channel-specific placeholders"""
        # Setup mocks
        mock_slack.get_message_content.return_value = {
            'user': 'U123456',
            'text': 'Here is my error log with lots of text'
        }

        # Create event
        event = {
            'item': {
                'channel': 'C123456',
                'ts': '1234567890.123456'
            },
            'reaction': 'error-log-to-thread-please'
        }
        
        # Create reaction config with placeholders
        reaction_config = {
            'message': "Removing the message. Follow <{link}|these recommendations>. Here's the original message:\n\n> {user_message}",
            'type': 'REPOST_TO_THREAD_AND_DELETE',
            'placeholders': {
                'link': {
                    'course-ml-zoomcamp': 'https://datatalks.club/docs/courses/zoomcamp-logistics/asking-questions/',
                    'default': 'https://datatalks.club/docs/courses/zoomcamp-logistics/asking-questions/'
                }
            }
        }
        
        # Execute
        lambda_function.handle_repost_to_thread_and_delete(event, reaction_config)
        
        # Verify
        mock_slack.get_message_content.assert_called_once_with('C123456', '1234567890.123456')
        mock_slack.post_message_thread.assert_called_once()
        # Verify the posted message contains the original message
        posted_message = mock_slack.post_message_thread.call_args[0][1]
        self.assertIn('Here is my error log with lots of text', posted_message)
    
    @patch('automator_lambda_function.slack')
    def test_repost_without_placeholders(self, mock_slack):
        """Test REPOST_TO_THREAD_AND_DELETE without placeholders"""
        # Setup mocks
        mock_slack.get_message_content.return_value = {
            'user': 'U123456',
            'text': 'Error message here'
        }
        
        # Create event
        event = {
            'item': {
                'channel': 'C123456',
                'ts': '1234567890.123456'
            },
            'reaction': 'error-log-to-thread-please'
        }
        
        # Create reaction config without placeholders
        reaction_config = {
            'message': 'Removing from channel. Original message:\n\n> {user_message}',
            'type': 'REPOST_TO_THREAD_AND_DELETE'
        }
        
        # Execute
        lambda_function.handle_repost_to_thread_and_delete(event, reaction_config)
        
        # Verify
        mock_slack.post_message_thread.assert_called_once()
        posted_message = mock_slack.post_message_thread.call_args[0][1]
        self.assertIn('Error message here', posted_message)
    
    @patch('automator_lambda_function.slack')
    def test_repost_message_not_found(self, mock_slack):
        """Test REPOST_TO_THREAD_AND_DELETE handles missing message gracefully"""
        # Setup mocks - message not found
        mock_slack.get_message_content.return_value = None
        
        # Create event
        event = {
            'item': {
                'channel': 'C123456',
                'ts': '1234567890.123456'
            },
            'reaction': 'error-log-to-thread-please'
        }
        
        # Create reaction config
        reaction_config = {
            'message': 'Message: {user_message}',
            'type': 'REPOST_TO_THREAD_AND_DELETE'
        }
        
        # Execute
        lambda_function.handle_repost_to_thread_and_delete(event, reaction_config)
        
        # Verify - should not post or delete when message not found
        mock_slack.post_message_thread.assert_not_called()
        mock_slack.remove_message.assert_not_called()
    
    @patch('automator_lambda_function.slack')
    def test_repost_no_user(self, mock_slack):
        """Test REPOST_TO_THREAD_AND_DELETE handles missing user gracefully"""
        # Setup mocks - message without user
        mock_slack.get_message_content.return_value = {
            'text': 'Bot message without user'
        }
        
        # Create event
        event = {
            'item': {
                'channel': 'C123456',
                'ts': '1234567890.123456'
            },
            'reaction': 'error-log-to-thread-please'
        }
        
        # Create reaction config
        reaction_config = {
            'message': 'Message: {user_message}',
            'type': 'REPOST_TO_THREAD_AND_DELETE'
        }
        
        # Execute
        lambda_function.handle_repost_to_thread_and_delete(event, reaction_config)
        
        # Verify - should not post or delete when no user
        mock_slack.post_message_thread.assert_not_called()
        mock_slack.remove_message.assert_not_called()
    
    @patch('automator_lambda_function.slack')
    def test_repost_with_curly_braces_in_message(self, mock_slack):
        """Test REPOST_TO_THREAD_AND_DELETE handles curly braces in user message"""
        # Setup mocks - message with curly braces
        mock_slack.get_message_content.return_value = {
            'user': 'U123456',
            'text': 'How to configure {POSTGRES_DB} and {POSTGRES_USER}?'
        }
        
        # Create event
        event = {
            'item': {
                'channel': 'C123456',
                'ts': '1234567890.123456'
            },
            'reaction': 'error-log-to-thread-please'
        }
        
        # Create reaction config
        reaction_config = {
            'message': 'Original: {user_message}',
            'type': 'REPOST_TO_THREAD_AND_DELETE'
        }
        
        # Execute - should not raise KeyError
        lambda_function.handle_repost_to_thread_and_delete(event, reaction_config)
        
        # Verify
        mock_slack.post_message_thread.assert_called_once()
        posted_message = mock_slack.post_message_thread.call_args[0][1]
        # Should contain the escaped braces
        self.assertIn('POSTGRES_DB', posted_message)
        self.assertIn('POSTGRES_USER', posted_message)
    
    @patch('automator_lambda_function.slack')
    def test_repost_placeholder_returns_none(self, mock_slack):
        """Test REPOST_TO_THREAD_AND_DELETE handles placeholder matching failure gracefully"""
        # Setup mocks
        mock_slack.get_message_content.return_value = {
            'user': 'U123456',
            'text': 'Error message'
        }

        # Create event
        event = {
            'item': {
                'channel': 'C123456',
                'ts': '1234567890.123456'
            },
            'reaction': 'error-log-to-thread-please'
        }
        
        # Create reaction config with placeholders but no default
        reaction_config = {
            'message': 'Message with {link}',
            'type': 'REPOST_TO_THREAD_AND_DELETE',
            'placeholders': {
                'link': {
                    'course-ml-zoomcamp': 'https://example.com'
                    # No default value
                }
            }
        }
        
        # Execute
        lambda_function.handle_repost_to_thread_and_delete(event, reaction_config)
        
        # Verify - should not post or delete when placeholder matching fails
        mock_slack.post_message_thread.assert_not_called()
        mock_slack.remove_message.assert_not_called()


class TestBanUser(unittest.TestCase):
    """Test BAN_USER handler"""

    def _base_reaction_config(self):
        return {
            'type': 'BAN_USER',
            'lookback_hours': 24,
            'reply_message': (
                "Hi <@{user}>! Your message in <#{channel}> was removed.\n\n"
                "> {user_message}\n"
            ),
            'admin_message': (
                "Ban cleanup for <@{target_user}>.\n"
                "ID: {target_user_id}\n"
                "Name: {display_name} / {real_name}\n"
                "Email: {email}\n"
                "Updated: {updated}\n"
                "Deleted: {deleted_count} parents, {thread_deleted_count} replies\n"
                "Admin: {admin_url}"
            ),
        }

    @patch('automator_lambda_function.slack')
    def test_ban_user_happy_path(self, mock_slack):
        """Search finds messages, replies notified, admin gets summary."""
        mock_slack.get_message_content.return_value = {
            'user': 'U_SPAMMER',
            'text': 'spam message',
        }
        mock_slack.get_user_info.return_value = {
            'id': 'U_SPAMMER',
            'name': 'spammer',
            'updated': 1700000000,
            'profile': {
                'display_name': 'Spammer',
                'real_name': 'Spam McSpamface',
                'email': 'spam@example.com',
            },
        }
        # One parent (the reacted one) + one stray reply from spammer elsewhere
        mock_slack.search_user_messages.return_value = [
            {
                'channel': {'id': 'C_AAA'},
                'ts': '1234567890.000100',
                'text': 'spam parent',
            },
            {
                'channel': {'id': 'C_BBB'},
                'ts': '1234567890.000200',
                'thread_ts': '1234567890.000150',  # reply in someone else's thread
                'text': 'spam reply',
            },
        ]
        # The spammer's parent has two replies: one from another user, one from spammer
        mock_slack.get_thread_replies.return_value = [
            {'user': 'U_VICTIM', 'ts': '1234567890.000101', 'text': 'innocent reply'},
            {'user': 'U_SPAMMER', 'ts': '1234567890.000102', 'text': 'spammer follow-up'},
        ]

        event = {
            'user': 'UMOD',
            'item': {'channel': 'C_AAA', 'ts': '1234567890.000100'},
            'reaction': 'ban-user',
        }

        # Use real time so cutoff doesn't filter our test messages
        with patch('automator_lambda_function.time.time', return_value=1234567890.0 + 1000), \
             patch('automator_lambda_function.FAKE_DELETE', False):
            lambda_function.handle_ban_user(event, self._base_reaction_config())

        # Victim got a DM; spammer did NOT. Moderator also gets an ID-only DM.
        dm_targets = [c.args[0] for c in mock_slack.send_dm.call_args_list]
        self.assertIn('U_VICTIM', dm_targets)
        self.assertIn('UMOD', dm_targets)
        self.assertNotIn('U_SPAMMER', dm_targets)
        # Moderator got the admin summary DM with blocks
        mock_slack.send_dm_blocks.assert_called_once()
        self.assertEqual(mock_slack.send_dm_blocks.call_args.args[0], 'UMOD')

        # All 4 messages deleted: parent + victim reply + spammer reply + stray reply
        deleted_keys = {
            (c.args[0], c.args[1]) for c in mock_slack.remove_message.call_args_list
        }
        self.assertEqual(
            deleted_keys,
            {
                ('C_AAA', '1234567890.000100'),
                ('C_AAA', '1234567890.000101'),
                ('C_AAA', '1234567890.000102'),
                ('C_BBB', '1234567890.000200'),
            },
        )

        # Admin summary should mention the spammer's ID and counts
        admin_dm = mock_slack.send_dm_blocks.call_args.args[1]
        self.assertIn('U_SPAMMER', admin_dm)
        self.assertIn('spam@example.com', admin_dm)
        self.assertIn('https://datatalks-club.slack.com/admin', admin_dm)
        admin_blocks = mock_slack.send_dm_blocks.call_args.args[2]
        self.assertIn('```U_SPAMMER```', admin_blocks[1]['text']['text'])
        self.assertEqual(
            admin_blocks[2]['elements'][0]['url'],
            'https://datatalks-club.slack.com/admin',
        )
        self.assertEqual(admin_blocks[2]['elements'][0]['value'], 'U_SPAMMER')
        id_only_dm = next(c.args[1] for c in mock_slack.send_dm.call_args_list if c.args[0] == 'UMOD')
        self.assertEqual(id_only_dm, 'U_SPAMMER')

    @patch('automator_lambda_function.slack')
    def test_ban_user_refuses_admin(self, mock_slack):
        """Should never act when target is an admin in config."""
        mock_slack.get_message_content.return_value = {
            'user': 'U01AXE0P5M3',  # admin from config.yaml
            'text': 'whatever',
        }
        event = {
            'user': 'UMOD',
            'item': {'channel': 'C_AAA', 'ts': '1234567890.000100'},
            'reaction': 'ban-user',
        }
        lambda_function.handle_ban_user(event, self._base_reaction_config())
        mock_slack.search_user_messages.assert_not_called()
        mock_slack.remove_message.assert_not_called()
        mock_slack.send_dm.assert_not_called()

    @patch('automator_lambda_function.slack')
    def test_ban_user_no_messages_still_dms_admin(self, mock_slack):
        """If search misses, still delete the reacted message and DM moderator."""
        mock_slack.get_message_content.return_value = {
            'user': 'U_SPAMMER',
            'text': 'spam',
        }
        mock_slack.get_user_info.return_value = {
            'name': 'spammer',
            'profile': {'display_name': 'Spammer'},
        }
        mock_slack.search_user_messages.return_value = []

        event = {
            'user': 'UMOD',
            'item': {'channel': 'C_AAA', 'ts': '1234567890.000100'},
            'reaction': 'ban-user',
        }
        with patch('automator_lambda_function.FAKE_DELETE', False):
            lambda_function.handle_ban_user(event, self._base_reaction_config())

        mock_slack.remove_message.assert_called_once_with(
            'C_AAA', '1234567890.000100'
        )
        mock_slack.send_dm.assert_called_once_with('UMOD', 'U_SPAMMER')
        mock_slack.send_dm_blocks.assert_called_once()
        self.assertEqual(mock_slack.send_dm_blocks.call_args.args[0], 'UMOD')
        self.assertIn('U_SPAMMER', mock_slack.send_dm_blocks.call_args.args[1])
        self.assertIn(
            'Deleted: 1 parents, 0 replies',
            mock_slack.send_dm_blocks.call_args.args[1],
        )

    @patch('automator_lambda_function.slack')
    def test_ban_user_delete_failure_not_counted(self, mock_slack):
        """Slack delete failures should not be counted as deleted messages."""
        mock_slack.get_message_content.return_value = {
            'user': 'U_SPAMMER',
            'text': 'spam',
        }
        mock_slack.get_user_info.return_value = {
            'name': 'spammer',
            'profile': {'display_name': 'Spammer'},
        }
        mock_slack.search_user_messages.return_value = []
        mock_slack.remove_message.return_value = {
            'ok': False,
            'error': 'cant_delete_message',
        }

        event = {
            'user': 'UMOD',
            'item': {'channel': 'C_AAA', 'ts': '1234567890.000100'},
            'reaction': 'ban-user',
        }
        with patch('automator_lambda_function.FAKE_DELETE', False):
            lambda_function.handle_ban_user(event, self._base_reaction_config())

        mock_slack.remove_message.assert_called_once_with(
            'C_AAA', '1234567890.000100'
        )
        self.assertIn(
            'Deleted: 0 parents, 0 replies',
            mock_slack.send_dm_blocks.call_args.args[1],
        )

    def test_ban_reaction_config_loaded(self):
        reaction_config = lambda_function.reaction_configs.get('ban-user')
        self.assertIsNotNone(reaction_config)
        self.assertEqual(reaction_config['type'], 'BAN_USER')
        self.assertIn('reply_message', reaction_config)
        self.assertIn('admin_message', reaction_config)

    def test_action_handlers_has_ban_user(self):
        self.assertIn('BAN_USER', lambda_function.action_handlers)
        self.assertEqual(
            lambda_function.action_handlers['BAN_USER'],
            lambda_function.handle_ban_user,
        )


class TestFaqAssistant(unittest.TestCase):
    """Test Cloudflare FAQ assistant integration."""

    def test_build_course_payload_from_known_channel(self):
        event = {
            'type': 'app_mention',
            'channel': 'C06TEGTGM3J',
            'text': '<@UFAQBOT> Can I still join after the course started?',
        }

        payload = lambda_function.build_faq_assistant_payload(event)

        self.assertEqual(payload['question'], 'Can I still join after the course started?')
        self.assertEqual(payload['scope'], 'course')
        self.assertEqual(payload['course'], 'llm-zoomcamp')

    def test_build_docs_payload_from_unknown_channel(self):
        event = {
            'type': 'app_mention',
            'channel': 'C_UNKNOWN',
            'text': '<@UFAQBOT> How do I join Slack?',
        }

        payload = lambda_function.build_faq_assistant_payload(event)

        self.assertEqual(payload['question'], 'How do I join Slack?')
        self.assertEqual(payload['scope'], 'docs')
        self.assertNotIn('course', payload)

    @patch('automator_lambda_function.requests.post')
    def test_call_faq_assistant_sends_shared_secret_header(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {'answer': 'answer'}
        mock_post.return_value = mock_response

        with patch('automator_lambda_function.FAQ_ASSISTANT_URL', 'https://worker.example.com'):
            with patch('automator_lambda_function.FAQ_ASSISTANT_SHARED_SECRET', 'secret-value'):
                result = lambda_function.call_faq_assistant({'question': 'q', 'scope': 'docs'})

        self.assertEqual(result, {'answer': 'answer'})
        mock_post.assert_called_once_with(
            'https://worker.example.com/ask',
            json={'question': 'q', 'scope': 'docs'},
            headers={'x-faq-assistant-secret': 'secret-value'},
            timeout=lambda_function.FAQ_ASSISTANT_TIMEOUT,
        )
        mock_response.raise_for_status.assert_called_once()

    @patch('automator_lambda_function.slack')
    @patch('automator_lambda_function.call_faq_assistant')
    def test_handle_app_mention_posts_answer_to_thread(self, mock_call, mock_slack):
        mock_call.return_value = {
            'answer': 'See [FAQ](https://datatalks.club/faq/).'
        }
        mock_slack.github_to_slack_markdown.return_value = (
            'See <https://datatalks.club/faq/|FAQ>.'
        )
        event = {
            'type': 'app_mention',
            'channel': 'C06TEGTGM3J',
            'text': '<@UFAQBOT> Can I still join?',
            'ts': '1790000000.000100',
        }

        lambda_function.handle_app_mention(event)

        mock_call.assert_called_once_with({
            'question': 'Can I still join?',
            'scope': 'course',
            'course': 'llm-zoomcamp',
        })
        mock_slack.post_message_to_thread.assert_called_once_with(
            'C06TEGTGM3J',
            '1790000000.000100',
            'See <https://datatalks.club/faq/|FAQ>.',
        )

    def test_faq_reaction_config_uses_faq_assistant(self):
        reaction_config = lambda_function.reaction_configs.get('faq')
        self.assertIsNotNone(reaction_config)
        self.assertEqual(reaction_config['type'], 'FAQ_ASSISTANT')

    def test_action_handlers_has_faq_assistant(self):
        self.assertIn('FAQ_ASSISTANT', lambda_function.action_handlers)
        self.assertEqual(
            lambda_function.action_handlers['FAQ_ASSISTANT'],
            lambda_function.handle_faq_assistant_reaction,
        )

    @patch('automator_lambda_function.slack')
    @patch('automator_lambda_function.call_faq_assistant')
    def test_handle_faq_reaction_posts_answer_to_original_thread(self, mock_call, mock_slack):
        mock_slack.get_message.return_value = (
            'UQUESTION',
            'Can I still join after the course started?',
        )
        mock_call.return_value = {
            'answer': 'Yes, you can still join.'
        }
        mock_slack.github_to_slack_markdown.return_value = 'Yes, you can still join.'
        event = {
            'type': 'reaction_added',
            'reaction': 'faq',
            'item': {
                'channel': 'C06TEGTGM3J',
                'ts': '1790000000.000100',
            },
        }

        lambda_function.handle_faq_assistant_reaction(event, {'type': 'FAQ_ASSISTANT'})

        mock_call.assert_called_once_with({
            'question': 'Can I still join after the course started?',
            'scope': 'course',
            'course': 'llm-zoomcamp',
        })
        mock_slack.post_message_to_thread.assert_called_once_with(
            'C06TEGTGM3J',
            '1790000000.000100',
            'Yes, you can still join.',
        )


if __name__ == '__main__':
    unittest.main()
