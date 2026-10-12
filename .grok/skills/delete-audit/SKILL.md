---
name: delete-audit
description: >
  Query Slack automator delete/ban audit records (who triggered a wipe, which
  reaction, which messages). Use when the user asks what was deleted, who was
  banned, delete-audit history, or runs /delete-audit.
---

# Delete-audit query

The automator records every delete (`DELETE_MESSAGE`, `BAN_USER`,
`REPOST_TO_THREAD_AND_DELETE`, `REMOVE_BROADCAST`, `CROSS_CHANNEL_SPAM`) with
the trigger, target user, and message text.

Schema, storage, and cost: `docs/delete-audit.md` in
`/home/alexey/git/au-tomator-lambda`. Do not restate it.

## Credentials

Default AWS Gate vends **sandbox** `817685572750` only. The table and bucket
are in **main** `387546586013`. Sandbox and `cmp-alert-investigator` cannot
`dynamodb:Query` this table.

Need main-account operator credentials (Alexey applying `main/automator`, or a
role that can read the table and bucket). If Gate is closed or the caller is
sandbox-only, say so and stop; do not guess records.

## Query

From `/home/alexey/git/au-tomator-lambda/automator`:

```bash
uv run python scripts/query_delete_audit.py --user U123
uv run python scripts/query_delete_audit.py --date YYYY-MM-DD
uv run python scripts/query_delete_audit.py --user U123 --s3
```

`--user` is the **target** Slack id (the person whose messages were removed),
not the admin who reacted. `--s3` is the forever copy after the 90-day Dynamo
TTL.

If the script is missing, use:

- Dynamo `automator-delete-audit` `eu-west-1`
  - `pk = USER#<slack_user_id>`
  - GSI `gsi1` `gsi1pk = DATE#YYYY-MM-DD`
- S3 `dtc-automator-delete-audit-387546586013` prefixes `by-user/<id>/` and
  `by-date/YYYY/MM/DD/`

## How to report

Show `recorded_at`, `action_type`, `reaction`, `triggered_by`,
`target_user_id`, counts, and message text. For a ban/spam wipe, list each
deleted message (channel, ts, kind, text). Do not dump emails unless asked.
