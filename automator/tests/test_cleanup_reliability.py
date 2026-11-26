"""Regression fixtures: never call real Slack or Lambda."""
from unittest.mock import MagicMock, patch, call
import pytest
from test_automator_lambda import lambda_function as app
import slack


def response(data):
    return MagicMock(json=lambda: data)


def test_thread_pagination_and_audit_fetch_reach_late_reply():
    pages = [
        {'ok': True, 'messages': [{'ts': '100', 'user': 'US'}, {'ts': '101'}],
         'has_more': True, 'response_metadata': {'next_cursor': 'page2'}},
        {'ok': True, 'messages': [{'ts': '102', 'user': 'UCHILD'}]},
    ]
    with patch.object(slack, '_conversations_get', side_effect=pages) as get:
        assert [m['ts'] for m in slack.get_thread_replies('C', '100')] == ['101', '102']
        assert get.call_args.args[1]['cursor'] == 'page2'
    with patch.object(slack, '_conversations_get', side_effect=pages):
        assert slack.get_message_content('C', '102', thread_ts='100')['user'] == 'UCHILD'


def test_incomplete_thread_read_is_not_an_empty_thread():
    with patch.object(slack, '_conversations_get', return_value={
        'ok': True, 'messages': [{'ts': '100'}], 'has_more': True,
    }):
        with pytest.raises(RuntimeError, match='incomplete pagination'):
            slack.get_thread_replies('C', '100')


def test_search_page_failure_is_not_partial_success():
    pages = [response({'ok': True, 'messages': {'matches': [{'ts': '100'}], 'paging': {'pages': 2}}}),
             response({'ok': False, 'error': 'ratelimited'})]
    with patch.object(slack.requests, 'get', side_effect=pages):
        with pytest.raises(RuntimeError, match='ratelimited'):
            slack.search_user_messages('spammer', '2026-11-20', user_id='US')


def test_history_finds_unindexed_spam_and_filters_other_authors():
    def get(method, params):
        if method == 'conversations.list':
            return {'ok': True, 'channels': [{'id': 'C'}]}
        if method == 'conversations.history':
            assert 'oldest' not in params
            return {'ok': True, 'messages': [
                {'user': 'US', 'ts': '101', 'reply_count': 2},
                {'user': 'UOTHER', 'ts': '50', 'reply_count': 1, 'latest_reply': '105'}, {'user': 'UOTHER', 'ts': '102'}]}
        if params['ts'] == '50':
            return {'ok': True, 'messages': [{'user': 'US', 'ts': '105', 'thread_ts': '50'}]}
        return {'ok': True, 'messages': [
            {'user': 'US', 'ts': '101'}, {'user': 'US', 'ts': '103', 'thread_ts': '101'},
            {'user': 'UOTHER', 'ts': '104', 'thread_ts': '101'}]}
    with patch.object(slack, '_conversations_get', side_effect=get):
        assert [m['ts'] for m in slack.recent_user_messages('US', 100)] == ['101', '103', '105']


def ban_event():
    return {'event_id': 'E_RETRY_FIXTURE', 'event': {
        'type': 'reaction_added', 'reaction': 'ban-user', 'user': 'UMOD', 'item_user': 'US',
        'item': {'channel': 'C', 'ts': '100'},
    }}


def test_partial_ban_retries_same_event_and_keeps_parent_until_children_removed():
    app._seen_event_ids.clear()
    with patch.object(app, 'slack') as api, patch.object(app, 'FAKE_DELETE', False):
        api.get_message_content.return_value = {'ts': '100', 'user': 'US'}
        api.get_user_info.return_value = {}
        api.search_user_messages.return_value = []
        api.recent_user_messages.return_value = []
        api.get_thread_replies.return_value = [{'ts': '101', 'user': 'UCHILD'}]
        api.remove_message.side_effect = [{'ok': False, 'error': 'ratelimited'}, {'ok': True}, {'ok': True}]
        with pytest.raises(RuntimeError, match='incomplete'):
            app.run(ban_event())
        assert api.remove_message.call_args_list == [call('C', '101', thread_ts='100')]
        assert 'INCOMPLETE' in api.send_dm_blocks.call_args.args[1]
        app.run(ban_event())
        assert api.remove_message.call_args_list[-1] == call('C', '100')
        assert api.remove_message.call_count == 3
        app.run(ban_event())
        assert api.remove_message.call_count == 3
    app._seen_event_ids.clear()


def test_ban_keeps_root_when_thread_read_fails_and_still_processes_other_spam():
    with patch.object(app, 'slack') as api, patch.object(app, 'FAKE_DELETE', False):
        api.get_message_content.return_value = {'ts': '100', 'user': 'US'}
        api.get_user_info.return_value = {}
        api.search_user_messages.return_value = []
        api.recent_user_messages.return_value = [{'channel': {'id': 'C2'}, 'ts': '200'}]
        api.get_thread_replies.side_effect = [RuntimeError('missing_scope'), []]
        with pytest.raises(RuntimeError, match='incomplete'):
            app.handle_ban_user(ban_event()['event'], {})
        api.remove_message.assert_called_once_with('C2', '200')


def test_delete_message_removes_bot_reply_with_thread_audit_context():
    with patch.object(app, 'slack') as api, patch.object(app, 'FAKE_DELETE', False):
        api.get_message_content.return_value = {'ts': '100', 'user': 'US', 'text': 'spam'}
        api.get_thread_replies.return_value = [{'ts': '101', 'bot_id': 'B1'}]
        app.handle_delete_message(ban_event()['event'], {
            'message': 'Removed', 'thread_message': 'Parent removed',
        })
        assert api.remove_message.call_args_list == [call('C', '101', thread_ts='100'), call('C', '100')]


def test_optional_thread_notification_does_not_prevent_delete():
    with patch.object(app, 'slack') as api, patch.object(app, 'FAKE_DELETE', False):
        api.get_message_content.return_value = {'ts': '100', 'user': 'US', 'text': 'spam'}
        api.get_thread_replies.return_value = [{'ts': '101', 'user': 'UCHILD'}]
        api.send_dm.side_effect = [RuntimeError('notification unavailable'), {'ok': True}]
        app.handle_delete_message(ban_event()['event'], {'message': 'Removed', 'thread_message': 'Parent removed'})
        assert api.remove_message.call_args_list == [call('C', '101', thread_ts='100'), call('C', '100')]


def test_retry_of_absent_message_requires_a_successful_read():
    with patch.object(app, 'slack') as api:
        api.remove_message.side_effect = RuntimeError('message unavailable for audit')
        api.is_message_absent.return_value = True
        with patch.object(app, 'FAKE_DELETE', False):
            assert app._delete_message('C', '100') is True
            api.is_message_absent.side_effect = RuntimeError('missing_scope')
            assert app._delete_message('C', '100') is False
    with patch.object(slack, '_conversations_get', return_value={'ok': True, 'messages': []}):
        assert slack.is_message_absent('C', '100') is True
    with patch.object(slack, '_conversations_get', return_value={'ok': False, 'error': 'missing_scope'}):
        with pytest.raises(RuntimeError, match='missing_scope'):
            slack.is_message_absent('C', '100')
