# AWS CloudWatch Logs

## Log Group Name

The automator lambda logs are stored in:
```
/aws/lambda/automator-process-reaction
```

## Viewing Logs via AWS CLI

### Using the "my" profile

The default credentials only allow lambda deployment. Use the `my` profile for logs:

```bash
# Last 2 hours of logs (calculate timestamp with node or date)
MSYS_NO_PATHCONV=1 aws logs filter-log-events \
  --log-group-name "/aws/lambda/automator-process-reaction" \
  --start-time 1770190542000 \
  --output text \
  --profile my
```

### Calculate start time

The `--start-time` is in milliseconds since epoch.

```bash
# Get current timestamp in milliseconds
node -e "console.log(Date.now())"

# Get timestamp from 1 hour ago (3600000 ms ago)
node -e "console.log(Date.now() - 3600000)"

# Get timestamp from 2 hours ago (7200000 ms ago)
node -e "console.log(Date.now() - 7200000)"
```

### Filter by pattern

```bash
# Search for specific reaction
MSYS_NO_PATHCONV=1 aws logs filter-log-events \
  --log-group-name "/aws/lambda/automator-process-reaction" \
  --start-time 1770190542000 \
  --filter-pattern "ask-ai" \
  --output text \
  --profile my
```

```bash
# Search for errors
MSYS_NO_PATHCONV=1 aws logs filter-log-events \
  --log-group-name "/aws/lambda/automator-process-reaction" \
  --start-time 1770190542000 \
  --filter-pattern "[ERROR]" \
  --output text \
  --profile my
```

### List all log groups

```bash
MSYS_NO_PATHCONV=1 aws logs describe-log-groups --output table --profile my
```

### Check Lambda environment variables

```bash
MSYS_NO_PATHCONV=1 aws lambda get-function-configuration \
  --function-name "automator-process-reaction" \
  --query 'Environment.Variables' \
  --output json \
  --profile my
```

## Windows/Git Bash Notes

On Windows with Git Bash, paths like `/aws/lambda/...` get converted to Windows paths. Always set `MSYS_NO_PATHCONV=1` before AWS logs commands.

## Alternative: AWS Console

1. Go to CloudWatch Logs in AWS Console
2. Navigate to `/aws/lambda/automator-process-reaction`
3. View logs in real-time or search

## FAQ assistant unavailable alert

When the FAQ assistant call fails, the bot still replies in the thread with the
"The FAQ assistant is currently not available" fallback, and logs one line
starting with `FAQ_ASSISTANT_UNAVAILABLE` (status, course, channel, error, body).

The CloudWatch metric filter `automator-faq-assistant-unavailable` (Terraform:
`aws-infra/main/automator/alerts.tf`) counts those lines into
`Automator/FaqAssistantUnavailable`. The alarm with the same name fires on any
occurrence in 5 minutes and notifies the `operator-alerts` SNS topic, which
emails dev@dtcdev.click (the oncall mailbox). Keep the marker token stable.

```bash
aws logs filter-log-events --log-group-name /aws/lambda/automator-process-reaction \
  --filter-pattern FAQ_ASSISTANT_UNAVAILABLE --start-time <ms>
```

To check the live FAQ assistant without posting to Slack, run the deploy
workflow with `faq_probe=true` (`gh workflow run deploy-automator.yml -f faq_probe=true`):
it reads the URL and shared secret from the Lambda config and requires a 200
answer from `/ask`.
