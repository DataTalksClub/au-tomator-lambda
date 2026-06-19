# Router Lambda

> **Status: ACTIVE.** Deployed as the Lambda function `slack-test` (override with
> the `ROUTER_FUNCTION_NAME` repo variable).

The router is the single entry point for Slack. Every event from Slack —
messages, emoji reactions, button clicks — hits this Lambda first. Slack expects
a response within ~3 seconds, so the router replies immediately and invokes the
right downstream Lambda **asynchronously** (the automator, or the moderator when
that route is enabled).

See the top-level [README](../README.md) for how the router, automator, and
moderator fit together.

## Layout

```
router/
├── src/            # Lambda code (handler: lambda_function.lambda_handler)
├── scripts/        # package.sh, deploy.sh, publish.sh
├── tests/          # unit tests
└── pyproject.toml  # self-contained deps (uv); no third-party runtime deps
```

## Develop & test

```bash
cd router
uv sync
uv run python -m unittest discover tests -v
```

## Deploy

```bash
cd router
bash scripts/publish.sh   # = package.sh + deploy.sh
```

CI does this automatically: `.github/workflows/deploy-router.yml` deploys after
`Test Router` passes on `main`. The deploy only runs when files under `router/`
change.
