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
retention (operationally configured). This is the immediate stopgap pending the
mod.dtcdev.click persistence API; it does not yet write to the app database.

```bash
cd automator
bash scripts/package.sh
bash scripts/deploy.sh
```

CI does this automatically: `.github/workflows/deploy-automator.yml` deploys
after `Test Automator` passes on `main`. The deploy only runs when files under
`automator/` change.
