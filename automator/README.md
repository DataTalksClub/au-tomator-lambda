# Automator Lambda

> **Status: ACTIVE.** Deployed as the Lambda function `automator-process-reaction`.

The automator does the actual work behind admin emoji reactions and FAQ
mentions. The router invokes it asynchronously:

- **Admin reactions** — when an admin reacts with a configured emoji, the
  automator looks up the action in `src/config.yaml` and runs it (repost to
  thread, delete, DM the author, etc.).
- **App mentions** — when anyone tags the bot, the automator can call the
  Cloudflare FAQ assistant and post the answer in the thread.

See the top-level [README](../README.md) for the configuration reference
(`src/config.yaml`) and the FAQ assistant setup.

## Live CMP context

Before a course FAQ answer, the bot makes one bounded GET to CMP's dedicated
`/api/bot/courses/<cohort>/state/` endpoint. Exact cohort mappings live under
`cmp.courses` in `src/config.yaml`; update them when the community changes
cohorts. No model selects tools and the bot never writes to CMP.

The FAQ assistant receives a strict public `course_state` object with homework
and project states, deadlines, peer-review availability, assignment existence,
fetch time and CMP source links. CMP has no scheduled review-opening timestamp;
the bot must not infer one from the submission deadline. The FAQ assistant must
support authenticated `course_state` requests before enabling this integration.

App mentions also request assignment counts using the configured Slack team and
the event's user ID. CMP matches only its verified Slack account link, never a
name or email. Counts are removed before calling the FAQ assistant and, for
peer-review/assignment questions, sent through `chat.postEphemeral` only to the
asker in the thread. Reaction requests fetch public state only. Unmapped users
still receive the public answer and can follow its CMP link to sign in.

Provision the dedicated `CMP_BOT_READ_TOKEN` GitHub secret and the
`CMP_SLACK_TEAM_ID` repository variable. Normal deployment preserves other
Lambda settings and installs these with `CMP_CONTEXT_ENABLED=1`; missing values
block deployment. The token has no authority over CMP's administrative API.
During local development the integration defaults off.

Fetches have 2-second connect and 5-second read timeouts, reject redirects,
cap the response at 64 KiB, and enforce a 7-second streaming deadline.
Deployment sets the Lambda timeout to 120 seconds to leave room for the existing
55-second FAQ request and the bounded CMP/alert calls.
Missing mappings/configuration, HTTP/validation
failures and private-delivery failures emit `CMP_CONTEXT_FAILED` and notify
configured admins in Slack; failed alerts emit `CMP_ALERT_DELIVERY_FAILED`.
CMP failures continue with the existing FAQ request. Alert and private-count
delivery also use bounded timeouts. No credentials, response bodies or private
counts are logged by this integration.

## Layout

```
automator/
├── src/            # Lambda code + config.yaml (handler: lambda_function.lambda_handler)
├── scripts/        # package.sh, deploy.sh
├── tests/          # unit tests + end-to-end reaction-routing tests (mocked Slack)
└── pyproject.toml  # self-contained deps (uv)
```

## Develop & test

```bash
cd automator
uv sync
uv run python -m unittest discover tests -v
```

## Deploy

Every real `chat.delete` first fetches the complete Slack message and emits a
single JSON line tagged `AUDIT_DELETED_MESSAGE`, containing the message (including
file metadata), channel, timestamps, author, reacting admin, and reaction. If the
message cannot be fetched or the audit cannot be logged, deletion is stopped.
This applies to template actions, `:delete:`, thread replies, and ban sweeps.
The production log group `/aws/lambda/automator-process-reaction` has 3653-day
retention (operationally configured). It also serves as a fallback journal.

Before deleting, the client writes to `POST /api/v1/deleted-messages` on
`https://mod.dtcdev.click` using the app's v1 contract. Two failed attempts stop
deletion and alert the reacting moderator and configured admins through Slack.
Only a matching `committed=true` response permits deletion. After successful
deletion, `AUDIT_DELETE_RECEIPT` is logged before posting the receipt to the app.
The reconciliation workflow replays the last seven days every 15 minutes;
manual dispatch supports up to 3653 days after longer outages. It requires
`logs:FilterLogEvents` on the production log group for the workflow's OIDC role.

Provision the private per-client `MOD_API_TOKEN` as a GitHub repository secret.
The normal deploy workflow preserves existing Lambda environment variables,
sets `MOD_AUDIT_ENABLED=true`, `MOD_API_URL=https://mod.dtcdev.click`, and the
token, and rejects missing/disabled configuration before updating code.
Do not deploy this integration before the app API is ready. There is no
runtime switch to bypass the app audit requirement. The app owns no-TTL
retention, backups, training access and receipt reconciliation alerts.

```bash
cd automator
bash scripts/package.sh
bash scripts/deploy.sh
```

CI does this automatically: `.github/workflows/deploy-automator.yml` deploys
after `Test Automator` passes on `main`. The deploy only runs when files under
`automator/` change.
