import os
os.environ['FAKE_DELETE'] = '1'
os.environ['CONFIG_FILE'] = '../automator/config.yaml'

import sys
sys.path.append('../automator')


import json

import lambda_function

with open('event.json') as f_in:
    event_template = json.load(f_in) 


def trigger_reaction(reaction):
    event = event_template.copy()
    event['event']['reaction'] = reaction
    lambda_function.lambda_handler(event, None)


def trigger_reaction_for_channel(reaction, channel_name):
    event = event_template.copy()
    event['event']['reaction'] = reaction

    # faking the channel name
    channel_id = event['event']['item']['channel']
    lambda_function.config['channels'][channel_id] = channel_name

    lambda_function.lambda_handler(event, None)


def test_dont_ask_to_ask_just_ask():
    trigger_reaction('dont-ask-to-ask-just-ask')


def test_thread():
    trigger_reaction('thread')


def test_faq_de_zoomcamp():
    trigger_reaction_for_channel('faq', 'course-data-engineering')


def test_faq_ml_zoomcamp():
    trigger_reaction_for_channel('faq', 'course-ml-zoomcamp')


def test_faq_other_channel():
    trigger_reaction_for_channel('faq', 'general')
    # nothing happens - no "default"


def test_error_log_to_thread_please_de_zoomcamp():
    trigger_reaction_for_channel('error-log-to-thread-please', 'course-data-engineering')


def test_error_log_to_thread_please_ml_zoomcamp():
    trigger_reaction_for_channel('error-log-to-thread-please', 'course-ml-zoomcamp')


def test_error_log_to_thread_please_other_channel():
    trigger_reaction_for_channel('error-log-to-thread-please', 'general')
    # should send a default message


def test_error_log_to_thread_and_delete_de_zoomcamp():
    trigger_reaction_for_channel('error-log-to-thread-and-delete', 'course-data-engineering')


def test_error_log_to_thread_and_delete_ml_zoomcamp():
    trigger_reaction_for_channel('error-log-to-thread-and-delete', 'course-ml-zoomcamp')


def test_error_log_to_thread_and_delete_other_channel():
    trigger_reaction_for_channel('error-log-to-thread-and-delete', 'general')
    # should send a default message and delete


def test_no_screenshot_de_zoomcamp():
    trigger_reaction_for_channel('no-screenshot', 'course-data-engineering')


def test_no_screenshot_other_channel():
    trigger_reaction_for_channel('no-screenshot', 'general')


def test_shameless_rules():
    trigger_reaction('shameless-rules')
    # should get a message and see a fake delete


def test_jobs_rules():
    trigger_reaction('jobs-rules')
    # should get a message and see a fake delete


def test_ask_in_course_channel():
    trigger_reaction('ask-in-course-channel')
    # should get a message and see a fake delete


def test_to_welcome():
    trigger_reaction('to-welcome')
    # should get a message and see a fake delete


def test_delete():
    trigger_reaction('delete')
    # should get a message to parent and thread authors and see fake deletes


def test_ask_ai():
    trigger_reaction('ask-ai')


def run():
    # test_dont_ask_to_ask_just_ask()
    # test_thread()
    # test_faq_de_zoomcamp()
    # test_faq_ml_zoomcamp()
    # test_faq_other_channel()
    # test_error_log_to_thread_please_de_zoomcamp()
    # test_error_log_to_thread_please_ml_zoomcamp()
    # test_error_log_to_thread_please_other_channel()
    # test_error_log_to_thread_and_delete_de_zoomcamp()
    # test_error_log_to_thread_and_delete_ml_zoomcamp()
    # test_error_log_to_thread_and_delete_other_channel()
    # test_no_screenshot_de_zoomcamp()
    # test_no_screenshot_other_channel()
    # test_shameless_rules()
    # test_jobs_rules()
    # test_ask_in_course_channel()
    # test_ask_ai()
    # test_to_welcome()
    test_delete()


if __name__ == '__main__':
    run()