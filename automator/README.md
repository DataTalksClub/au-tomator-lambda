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
