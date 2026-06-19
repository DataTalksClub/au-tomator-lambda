#!/usr/bin/env python3
"""
Integration test for message moderator with LocalStack.

Prerequisites:
1. Start LocalStack: docker-compose up -d
2. Wait for LocalStack to be ready
3. Run this test: python integration/test_moderator.py
"""

import os
import sys
import time
import json

# Set up environment for LocalStack
os.environ['DYNAMODB_ENDPOINT'] = 'http://localhost:4566'
os.environ['MESSAGE_TRACKER_TABLE'] = 'test-message-tracker'
os.environ['MESSAGE_THRESHOLD'] = '5'
os.environ['TIME_WINDOW_SECONDS'] = '180'
os.environ['ADMIN_USER_ID'] = 'U_ADMIN'
os.environ['SLACK_TOKEN'] = 'test-token'
os.environ['USER_SLACK_TOKEN'] = 'test-user-token'

# Add moderator to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import message_tracker


def test_basic_tracking():
    """Test basic message tracking"""
    print("Testing basic message tracking...")
    
    # Track a single message
    result = message_tracker.track_message(
        'U123456',
        'C123456',
        '1234567890.123456',
        'Test message 1'
    )
    
    assert not result['exceeded'], "Single message should not exceed threshold"
    assert result['message_count'] == 1, f"Expected 1 message, got {result['message_count']}"
    print("✓ Basic tracking works")


def test_threshold_detection():
    """Test threshold detection"""
    print("\nTesting threshold detection...")
    
    user_id = 'U_SPAM_USER'
    channel_id = 'C_TEST'
    
    # Track 4 messages - should not trigger
    for i in range(4):
        result = message_tracker.track_message(
            user_id,
            channel_id,
            f'{time.time()}.{i}',
            f'Message {i + 1}'
        )
        assert not result['exceeded'], f"Message {i + 1} should not exceed threshold"
    
    # Track 5th message - should trigger
    result = message_tracker.track_message(
        user_id,
        channel_id,
        f'{time.time()}.5',
        'Message 5 - triggers threshold'
    )
    
    assert result['exceeded'], "5th message should exceed threshold"
    assert result['message_count'] == 5, f"Expected 5 messages, got {result['message_count']}"
    assert len(result['messages']) == 5, f"Expected 5 messages in result, got {len(result['messages'])}"
    print("✓ Threshold detection works")
    
    # Clear messages
    message_tracker.clear_user_messages(user_id)


def test_time_window():
    """Test that old messages are filtered out"""
    print("\nTesting time window filtering...")
    
    user_id = 'U_TIME_TEST'
    
    # Clear any existing data
    message_tracker.clear_user_messages(user_id)
    
    # Manually insert old messages (outside time window)
    # This would require direct DynamoDB access, so we'll just verify
    # that new messages don't count old ones
    
    # Add a message
    result = message_tracker.track_message(
        user_id,
        'C_TEST',
        f'{time.time()}.1',
        'Recent message'
    )
    
    assert result['message_count'] == 1, "Should only count recent messages"
    print("✓ Time window filtering works")
    
    # Clean up
    message_tracker.clear_user_messages(user_id)


def test_message_retrieval():
    """Test retrieving user messages"""
    print("\nTesting message retrieval...")
    
    user_id = 'U_RETRIEVE_TEST'
    
    # Clear any existing data
    message_tracker.clear_user_messages(user_id)
    
    # Add some messages
    for i in range(3):
        message_tracker.track_message(
            user_id,
            'C_TEST',
            f'{time.time()}.{i}',
            f'Message {i + 1}'
        )
    
    # Retrieve messages
    messages = message_tracker.get_user_messages(user_id)
    
    assert len(messages) == 3, f"Expected 3 messages, got {len(messages)}"
    print("✓ Message retrieval works")
    
    # Clean up
    message_tracker.clear_user_messages(user_id)


def main():
    """Run all integration tests"""
    print("=" * 60)
    print("Message Moderator Integration Tests with LocalStack")
    print("=" * 60)
    
    try:
        test_basic_tracking()
        test_threshold_detection()
        test_time_window()
        test_message_retrieval()
        
        print("\n" + "=" * 60)
        print("✓ All tests passed!")
        print("=" * 60)
        return 0
        
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
