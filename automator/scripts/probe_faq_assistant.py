"""Ask the live FAQ assistant one question the way the automator does.

Reads the automator Lambda environment JSON (FAQ_ASSISTANT_URL and
FAQ_ASSISTANT_SHARED_SECRET) on stdin, POSTs a course-scoped question to /ask
and fails unless it gets HTTP 200 with a non-empty answer. Nothing is posted to
Slack. The secret is never printed.
"""

import json
import sys

import requests

QUESTION = 'How do I submit the homework?'
COURSE = 'ai-dev-tools-zoomcamp'


def main() -> int:
    env = json.load(sys.stdin)
    url = (env.get('FAQ_ASSISTANT_URL') or '').strip().rstrip('/')
    secret = env.get('FAQ_ASSISTANT_SHARED_SECRET') or ''
    if secret:
        print(f'::add-mask::{secret}', flush=True)  # GitHub Actions log masking
    if not url:
        print('FAQ_ASSISTANT_URL is not set on the automator Lambda')
        return 1
    endpoint = url if url.endswith('/ask') else f'{url}/ask'
    headers = {'x-faq-assistant-secret': secret} if secret else {}
    response = requests.post(
        endpoint,
        json={'question': QUESTION, 'scope': 'course', 'course': COURSE},
        headers=headers,
        timeout=60,
    )
    print(f'HTTP {response.status_code}')
    if response.status_code != 200:
        print(response.text[:500])
        return 1
    body = response.json()
    answer = (body.get('answer') or '').strip()
    print(f"found_answer={body.get('found_answer')} sources={len(body.get('sources') or [])}")
    print(f'answer: {answer[:300]}')
    return 0 if answer else 1


if __name__ == '__main__':
    sys.exit(main())
