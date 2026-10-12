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

Delete / ban-user actions are recorded (trigger, target user, message text)
in DynamoDB + S3. See [docs/delete-audit.md](../docs/delete-audit.md). Query
them with `/delete-audit`.

Cross-channel copy-paste spam is pre-aggregated in DynamoDB (`spam.py`). A
5-minute EventBridge scan deletes quiet sessions and DMs Alexey the same
deactivate flow as `:ban-user:`. Requires `message.channels` on the Slack app
and the Dynamo/EventBridge resources in `aws-infra/main/automator`.

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

```bash
cd automator
bash scripts/package.sh
bash scripts/deploy.sh
```

CI does this automatically: `.github/workflows/deploy-automator.yml` deploys
after `Test Automator` passes on `main`. The deploy only runs when files under
`automator/` change.
