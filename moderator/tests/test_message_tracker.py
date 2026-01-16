import sys
import os
import unittest
from unittest.mock import patch, MagicMock
import time

# Add moderator directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'moderator'))

import message_tracker


class TestMessageTracker(unittest.TestCase):
    
    def setUp(self):
        """Set up test environment"""
        # Use LocalStack endpoint for testing
        os.environ['DYNAMODB_ENDPOINT'] = 'http://localhost:4566'
        os.environ['MESSAGE_TRACKER_TABLE'] = 'test-message-tracker'
        os.environ['MESSAGE_THRESHOLD'] = '5'
        os.environ['TIME_WINDOW_SECONDS'] = '180'
    
    @patch('message_tracker.ensure_table_exists')
    @patch('message_tracker.get_dynamodb_resource')
    def test_track_message_below_threshold(self, mock_get_resource, mock_ensure_table):
        """Test tracking a message that doesn't exceed threshold"""
        # Mock DynamoDB table
        mock_table = MagicMock()
        mock_table.get_item.return_value = {'Item': {'messages': []}}
        mock_ensure_table.return_value = mock_table
        
        result = message_tracker.track_message(
            'U123456',
            'C123456',
            '1234567890.123456',
            'Test message'
        )
        
        self.assertFalse(result['exceeded'])
        self.assertEqual(result['message_count'], 1)
        self.assertEqual(result['messages'], [])
    
    @patch('message_tracker.ensure_table_exists')
    @patch('message_tracker.get_dynamodb_resource')
    def test_track_message_exceeds_threshold(self, mock_get_resource, mock_ensure_table):
        """Test tracking messages that exceed threshold"""
        # Mock DynamoDB table with existing messages
        current_time = int(time.time())
        existing_messages = [
            {
                'timestamp': current_time - 60,
                'channel_id': 'C123456',
                'message_ts': f'{current_time - 60}.123456',
                'message_text': 'Message 1'
            },
            {
                'timestamp': current_time - 120,
                'channel_id': 'C123456',
                'message_ts': f'{current_time - 120}.123456',
                'message_text': 'Message 2'
            },
            {
                'timestamp': current_time - 150,
                'channel_id': 'C123456',
                'message_ts': f'{current_time - 150}.123456',
                'message_text': 'Message 3'
            },
            {
                'timestamp': current_time - 170,
                'channel_id': 'C123456',
                'message_ts': f'{current_time - 170}.123456',
                'message_text': 'Message 4'
            }
        ]
        
        mock_table = MagicMock()
        mock_table.get_item.return_value = {'Item': {'messages': existing_messages}}
        mock_ensure_table.return_value = mock_table
        
        result = message_tracker.track_message(
            'U123456',
            'C123456',
            '1234567890.123456',
            'Message 5 - triggers threshold'
        )
        
        self.assertTrue(result['exceeded'])
        self.assertEqual(result['message_count'], 5)
        self.assertEqual(len(result['messages']), 5)
    
    @patch('message_tracker.ensure_table_exists')
    @patch('message_tracker.get_dynamodb_resource')
    def test_old_messages_filtered_out(self, mock_get_resource, mock_ensure_table):
        """Test that messages older than time window are filtered out"""
        current_time = int(time.time())
        
        # Create messages, some within window, some outside
        existing_messages = [
            {
                'timestamp': current_time - 60,  # Within window
                'channel_id': 'C123456',
                'message_ts': f'{current_time - 60}.123456',
                'message_text': 'Recent message'
            },
            {
                'timestamp': current_time - 200,  # Outside window (> 180 seconds)
                'channel_id': 'C123456',
                'message_ts': f'{current_time - 200}.123456',
                'message_text': 'Old message'
            }
        ]
        
        mock_table = MagicMock()
        mock_table.get_item.return_value = {'Item': {'messages': existing_messages}}
        mock_ensure_table.return_value = mock_table
        
        result = message_tracker.track_message(
            'U123456',
            'C123456',
            '1234567890.123456',
            'New message'
        )
        
        # Should only count the recent message + new message = 2
        self.assertEqual(result['message_count'], 2)
        self.assertFalse(result['exceeded'])
    
    @patch('message_tracker.ensure_table_exists')
    @patch('message_tracker.get_dynamodb_resource')
    def test_clear_user_messages(self, mock_get_resource, mock_ensure_table):
        """Test clearing all messages for a user"""
        mock_table = MagicMock()
        mock_ensure_table.return_value = mock_table
        
        message_tracker.clear_user_messages('U123456')
        
        mock_table.delete_item.assert_called_once_with(Key={'user_id': 'U123456'})
    
    @patch('message_tracker.ensure_table_exists')
    @patch('message_tracker.get_dynamodb_resource')
    def test_get_user_messages(self, mock_get_resource, mock_ensure_table):
        """Test retrieving messages for a user"""
        messages = [
            {
                'timestamp': int(time.time()),
                'channel_id': 'C123456',
                'message_ts': '1234567890.123456',
                'message_text': 'Test message'
            }
        ]
        
        mock_table = MagicMock()
        mock_table.get_item.return_value = {'Item': {'messages': messages}}
        mock_ensure_table.return_value = mock_table
        
        result = message_tracker.get_user_messages('U123456')
        
        self.assertEqual(result, messages)


if __name__ == '__main__':
    unittest.main()
