"""Bounded GET of CMP state. No model-selected tools or CMP writes."""
import os
import re
from urllib.parse import urlparse

import requests

from logs import logger


BASE_URL = 'https://courses.datatalks.club'
PUBLIC_FIELDS = {
    'course': ('slug', 'title', 'source_url', 'starts_at', 'start_date', 'end_date', 'finished'),
    'homeworks': ('slug', 'title', 'state', 'starts_at', 'due_date', 'source_url'),
    'projects': ('slug', 'title', 'state', 'starts_at', 'submission_due_date',
                 'peer_review_due_date', 'peer_review_open', 'peer_review_opens_at',
                 'assignments_created', 'source_url'),
}


def _public_item(item, fields):
    if not isinstance(item, dict) or any(key not in item for key in fields):
        raise ValueError('Incomplete CMP state')
    result = {key: item[key] for key in fields}
    if any(isinstance(value, (dict, list)) for value in result.values()):
        raise ValueError('Invalid CMP field')
    source = urlparse(result['source_url'])
    if source.scheme != 'https' or source.netloc != 'courses.datatalks.club':
        raise ValueError('Invalid CMP source')
    return result


def fetch_state(cohort, user=None):
    token = os.getenv('CMP_BOT_READ_TOKEN', '')
    if not token:
        raise ValueError('CMP token missing')
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', cohort):
        raise ValueError('Invalid cohort')
    params = {}
    if user:
        team = os.getenv('CMP_SLACK_TEAM_ID', '')
        if not re.fullmatch(r'T[A-Z0-9]+', team):
            raise ValueError('CMP Slack team missing')
        if not re.fullmatch(r'U[A-Z0-9]+', user):
            raise ValueError('Invalid Slack user')
        params = {'slack_team_id': team, 'slack_user_id': user}
    with requests.get(
        f'{BASE_URL}/api/bot/courses/{cohort}/state/',
        params=params, headers={'Authorization': f'Bearer {token}'},
        timeout=(2, 5), allow_redirects=False, stream=True,
    ) as response:
        if response.status_code != 200:
            raise ValueError(f'CMP HTTP {response.status_code}')
        body = bytearray()
        for chunk in response.iter_content(8192):
            body.extend(chunk)
            if len(body) > 65536:
                raise ValueError('CMP response too large')
    import json
    state = json.loads(body)
    if state.get('schema_version') != 1 or state.get('course', {}).get('slug') != cohort:
        raise ValueError('CMP cohort/schema mismatch')
    public = {'schema_version': 1, 'fetched_at': state['fetched_at']}
    public['course'] = _public_item(state['course'], PUBLIC_FIELDS['course'])
    for key in ('homeworks', 'projects'):
        items = state[key]
        if not isinstance(items, list) or len(items) > 100:
            raise ValueError('Invalid CMP item count')
        public[key] = [_public_item(item, PUBLIC_FIELDS[key]) for item in items]
    # Private data never enters the LLM request, its traces, or the public reply.
    private = None
    student = state.get('student') or {}
    if user and student.get('mapped') is True:
        counts = student.get('projects')
        if not isinstance(counts, list) or len(counts) > 100:
            raise ValueError('Invalid CMP assignment counts')
        titles = {p['slug']: p['title'] for p in public['projects']}
        private = []
        for item in counts:
            count = item.get('assigned_count')
            pending = item.get('pending_count')
            if (item.get('slug') not in titles or type(count) is not int
                    or type(pending) is not int or not 0 <= pending <= count):
                raise ValueError('Invalid CMP assignment count')
            private.append(f"{titles[item['slug']]}: {count} assigned ({pending} pending).")
    return public, private


def alert(slack, admins, course, reason):
    # Never log exception text, response bodies, credentials, or student data.
    message = f'CMP_CONTEXT_FAILED: course={course} reason={reason}; FAQ fallback used.'
    logger.error(message)
    for admin in admins:
        try:
            slack.post_private_message(admin, message)
        except Exception:
            logger.error('CMP_ALERT_DELIVERY_FAILED')


def enrich(payload, config, slack, student_user=None):
    if os.getenv('CMP_CONTEXT_ENABLED', '0') != '1' or not payload.get('course'):
        return payload, None
    course = payload['course']
    cohort = (config.get('cmp') or {}).get('courses', {}).get(course)
    if not cohort:
        alert(slack, config.get('admins', []), course, 'unmapped_course')
        return payload, None
    try:
        public, private = fetch_state(cohort, student_user)
        return {**payload, 'course_state': public}, private
    except Exception as exc:
        alert(slack, config.get('admins', []), course, type(exc).__name__)
        return payload, None


def send_student_counts(slack, channel, thread_ts, user, payload, counts, admins):
    if counts is None or not re.search(r'peer[ -]?review|assign', payload['question'], re.I):
        return
    message = ('Your CMP peer-review assignments (visible only to you):\n'
               + '\n'.join(counts or ['No project assignments in this course.'])
               + f"\n<{payload['course_state']['course']['source_url']}|Open CMP>")
    try:
        slack.post_ephemeral(channel, user, thread_ts, message)
    except Exception as exc:
        alert(slack, admins, payload['course'], f'private_delivery_{type(exc).__name__}')
