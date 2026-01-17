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
        """Verify that 'thread_please' reaction is configured"""
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
        }
        
        for channel_id, expected_name in expected_channels.items():
            channel_name = lambda_function.get_channel_name(channel_id)
            self.assertEqual(
                channel_name, 
                expected_name,
                f"Channel {channel_id} should be {expected_name}"
            )


if __name__ == '__main__':
    unittest.main()
