"""Validate Lambda environment from stdin without printing its secrets."""
import json
import os
import sys

from deletion_audit import configuration


def main():
    try:
        environment = json.load(sys.stdin)
        if not isinstance(environment, dict):
            raise ValueError('environment missing')
        merge = '--merge' in sys.argv
        for key in ('MOD_AUDIT_ENABLED', 'MOD_API_URL', 'MOD_API_TOKEN'):
            if merge:
                environment[key] = os.environ.get(key, '')
            else:
                os.environ[key] = environment.get(key, '')
        configuration()
    except (ValueError, TypeError, RuntimeError):
        print('Deployment blocked: MOD_AUDIT_ENABLED=true, MOD_API_URL and MOD_API_TOKEN are required', file=sys.stderr)
        return 1
    if merge:
        json.dump({'Variables': environment}, sys.stdout)
    else:
        print('Deletion audit configuration validated')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
