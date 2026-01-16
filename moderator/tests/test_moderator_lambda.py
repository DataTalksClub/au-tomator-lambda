import sys
import os
import unittest
from unittest.mock import patch, MagicMock
import json

# Set environment before importing lambda_function
os.environ['ADMIN_USER_ID'] = 'U_ADMIN'

# Add moderator directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'moderator'))

import lambda_function


class TestModeratorLambda(unittest.TestCase):
    
    def test_challenge_response(self):
        """Test URL verification challenge"""
        event = {
            'challenge': 'test_challenge_token'
        }
        
        result = lambda_function.lambda_handler(event, None)
        
        self.assertEqual(result['statusCode'], 200)
        self.assertEqual(result['body'], 'test_challenge_token')
    
    @patch('lambda_function.message_tracker')
    @patch('lambda_function.slack_moderator')
    def test_message_event_below_threshold(self, mock_slack, mock_tracker):
        """Test handling message event below threshold"""
        mock_tracker.track_message.return_value = {
            'exceeded': False,
            'message_count': 3,
            'messages': []
        }
        
        event = {
            'event': {
                'type': 'message',
                'user': 'U123456',
                'channel': 'C123456',
                'ts': '1234567890.123456',
                'text': 'Test message'
            }
        }
        
        result = lambda_function.lambda_handler(event, None)
        
        self.assertEqual(result['statusCode'], 200)
        mock_tracker.track_message.assert_called_once()
        mock_slack.send_moderation_alert.assert_not_called()
    
    @patch('lambda_function.message_tracker')
    @patch('lambda_function.slack_moderator')
    def test_message_event_exceeds_threshold(self, mock_slack, mock_tracker):
        """Test handling message event that exceeds threshold"""
        messages = [
            {'timestamp': 123, 'channel_id': 'C123456', 'message_ts': '123.1', 'message_text': 'Msg 1'},
            {'timestamp': 124, 'channel_id': 'C123456', 'message_ts': '124.1', 'message_text': 'Msg 2'},
            {'timestamp': 125, 'channel_id': 'C123456', 'message_ts': '125.1', 'message_text': 'Msg 3'},
            {'timestamp': 126, 'channel_id': 'C123456', 'message_ts': '126.1', 'message_text': 'Msg 4'},
            {'timestamp': 127, 'channel_id': 'C123456', 'message_ts': '127.1', 'message_text': 'Msg 5'},
        ]
        
        mock_tracker.track_message.return_value = {
            'exceeded': True,
            'message_count': 5,
            'messages': messages
        }
        
        event = {
            'event': {
                'type': 'message',
                'user': 'U123456',
                'channel': 'C123456',
                'ts': '1234567890.123456',
                'text': 'Test message 5'
            }
        }
        
        result = lambda_function.lambda_handler(event, None)
        
        self.assertEqual(result['statusCode'], 200)
        mock_tracker.track_message.assert_called_once()
        mock_slack.send_moderation_alert.assert_called_once_with('U123456', messages)
    
    @patch('lambda_function.message_tracker')
    @patch('lambda_function.slack_moderator')
    def test_ignore_bot_messages(self, mock_slack, mock_tracker):
        """Test that bot messages are ignored"""
        event = {
            'event': {
                'type': 'message',
                'subtype': 'bot_message',
                'user': 'U123456',
                'channel': 'C123456',
                'ts': '1234567890.123456',
                'text': 'Bot message'
            }
        }
        
        result = lambda_function.lambda_handler(event, None)
        
        self.assertEqual(result['statusCode'], 200)
        mock_tracker.track_message.assert_not_called()
    
    @patch('lambda_function.message_tracker')
    @patch('lambda_function.slack_moderator')
    def test_ignore_admin_messages(self, mock_slack, mock_tracker):
        """Test that admin messages are ignored"""
        event = {
            'event': {
                'type': 'message',
                'user': 'U_ADMIN',
                'channel': 'C123456',
                'ts': '1234567890.123456',
                'text': 'Admin message'
            }
        }
        
        result = lambda_function.lambda_handler(event, None)
        
        self.assertEqual(result['statusCode'], 200)
        mock_tracker.track_message.assert_not_called()
    
    @patch('lambda_function.message_tracker')
    @patch('lambda_function.slack_moderator')
    def test_delete_messages_action(self, mock_slack, mock_tracker):
        """Test delete messages button action"""
        messages = [
            {'timestamp': 123, 'channel_id': 'C123456', 'message_ts': '123.1', 'message_text': 'Msg 1'},
            {'timestamp': 124, 'channel_id': 'C123456', 'message_ts': '124.1', 'message_text': 'Msg 2'},
        ]
        
        mock_tracker.get_user_messages.return_value = messages
        mock_slack.delete_messages.return_value = {
            'success': messages,
            'failed': []
        }
        
        payload = {
            'actions': [{
                'action_id': 'delete_messages',
                'value': 'U123456'
            }],
            'channel': {'id': 'C_ADMIN'},
            'container': {'message_ts': '9999999999.999999'}
        }
        
        event = {
            'payload': json.dumps(payload)
        }
        
        result = lambda_function.lambda_handler(event, None)
        
        self.assertEqual(result['statusCode'], 200)
        mock_tracker.get_user_messages.assert_called_once_with('U123456')
        mock_slack.delete_messages.assert_called_once_with(messages)
        mock_tracker.clear_user_messages.assert_called_once_with('U123456')
        mock_slack.update_alert_message.assert_called_once()
    
    @patch('lambda_function.message_tracker')
    @patch('lambda_function.slack_moderator')
    def test_ignore_alert_action(self, mock_slack, mock_tracker):
        """Test ignore alert button action"""
        payload = {
            'actions': [{
                'action_id': 'ignore_alert',
                'value': 'U123456'
            }],
            'channel': {'id': 'C_ADMIN'},
            'container': {'message_ts': '9999999999.999999'}
        }
        
        event = {
            'payload': json.dumps(payload)
        }
        
        result = lambda_function.lambda_handler(event, None)
        
        self.assertEqual(result['statusCode'], 200)
        mock_tracker.clear_user_messages.assert_called_once_with('U123456')
        mock_slack.update_alert_message.assert_called_once()


if __name__ == '__main__':
    unittest.main()
