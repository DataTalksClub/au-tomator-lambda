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
