# Delete-action audit

When an admin reaction deletes Slack messages, the automator records **what
was deleted**, **which reaction triggered it**, and **who triggered it**.

This is especially important for `:ban-user:`, which can wipe a user's recent
messages plus thread replies.

## What is stored

Each action is one record:

- `action_type` — `DELETE_MESSAGE`, `BAN_USER`, `REPOST_TO_THREAD_AND_DELETE`, `REMOVE_BROADCAST`, or `CROSS_CHANNEL_SPAM`
- `reaction` — emoji that triggered it (`delete`, `ban-user`, `shameless-rules`, …)
- `triggered_by` — Slack user id of the reacting admin
- `target_user_id` / `target_user` — author being acted on (id, name, email when known)
- `channel` / `channel_name` / `message_ts` — the reacted message
- `deleted_messages[]` — every message removed: channel, ts, user, text, kind (`parent` / `reply` / `broadcast`), whether Slack accepted the delete
- `extra` — for bans: lookback window and parent/reply counts

Message text is clipped at 4,000 characters.

## Where it lives (cheap)

Dual-written at event time. No extra dump job.

| Store | Retention | Cost | Use |
| --- | --- | --- | --- |
| CloudWatch log line `DELETE_AUDIT {json}` | whatever the Lambda log group keeps | already paying | last couple of weeks, Insights |
| DynamoDB `automator-delete-audit` (on-demand, TTL) | 90 days | ~$0 at this volume | query by user or by day |
| S3 Standard `dtc-automator-delete-audit-387546586013` | forever | a few KB per action | archive after Dynamo expires |

S3 stays in Standard on purpose. Glacier and Standard-IA bill a 128 KB
minimum per object; these files are a few KB, so Standard is cheaper.

Infra: `aws-infra/main/automator/audit.tf`. Apply that stack before expecting
Dynamo/S3 writes. Until then the Lambda still logs `DELETE_AUDIT` and
swallows storage errors so deletes keep working.

## Query

From `automator/`:

```bash
# Recent actions against one user (Dynamo, last 90 days)
uv run python scripts/query_delete_audit.py --user U123

# Everything on a calendar day
uv run python scripts/query_delete_audit.py --date 2026-04-08

# Forever copy in S3 (also works after Dynamo TTL)
uv run python scripts/query_delete_audit.py --user U123 --s3
```

## Last two weeks from existing logs

Current production logs **do not include deleted message bodies**. Each
invocation prints the Slack event (`print(json.dumps(body))`), which has:

- who reacted (`event.user`)
- which emoji (`event.reaction`)
- which channel / message ts (`event.item`)

It does **not** have the message text. After a delete, Slack no longer has
that text either. Historical recovery of *what was said* is not possible from
logs written before this audit existed.

Once AWS Gate is open on this host, search the last 14 days of triggers:

```bash
START_MS=$(python3 -c 'import time; print(int((time.time()-14*86400)*1000))')
aws logs filter-log-events \
  --log-group-name /aws/lambda/automator-process-reaction \
  --start-time "$START_MS" \
  --filter-pattern '"ban-user"' \
  --region eu-west-1
```

Useful filter patterns: `"ban-user"`, `"reaction": "delete"`, `shameless-rules`,
`jobs-rules`, `DELETE_AUDIT`.

## Production access for agents

AWS Gate vends the **sandbox** role (`817685572750`) only. The audit table and
bucket are in **main** (`387546586013`). `cmp-alert-investigator` cannot query
this table.

Query with main-account operator credentials, or `/delete-audit`. See
`.grok/skills/delete-audit/SKILL.md`.
