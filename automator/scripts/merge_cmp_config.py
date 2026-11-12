"""Merge dedicated read-only CMP settings into the deployment environment."""
import json
import os
import re
import sys


def main():
    try:
        environment = json.load(sys.stdin)
        values = environment['Variables']
        token = os.environ.get('CMP_BOT_READ_TOKEN', '').strip()
        team = os.environ.get('CMP_SLACK_TEAM_ID', '').strip()
        if not token or not re.fullmatch(r'T[A-Z0-9]+', team):
            raise ValueError('Missing dedicated CMP token or Slack team')
        values.update(CMP_CONTEXT_ENABLED='1', CMP_BOT_READ_TOKEN=token, CMP_SLACK_TEAM_ID=team)
        json.dump(environment, sys.stdout)
        return 0
    except (ValueError, KeyError, TypeError):
        print('Deployment blocked: CMP_BOT_READ_TOKEN and CMP_SLACK_TEAM_ID required', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
