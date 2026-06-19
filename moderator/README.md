# Message Moderator Lambda

> ⚠️ **Status: PARKED.** This project is not currently deployed — the router's
> message-moderation route is disabled and there is no deploy workflow. The code
> and tests are kept working (CI runs `Test Moderator`) so it can be revived. To
> reactivate, re-enable the router route and add a `deploy-moderator.yml`
> workflow mirroring `deploy-automator.yml`.

This Lambda function monitors message rate in Slack channels and alerts administrators when users exceed the configured threshold.

## Layout

```
moderator/
├── src/                  # Lambda code (handler: lambda_function.lambda_handler)
├── scripts/              # package.sh, deploy.sh
├── tests/                # unit tests
├── integration/          # LocalStack integration test
├── docker-compose.yml    # LocalStack for the integration test
├── pyproject.toml        # self-contained deps (uv)
└── SLACK_SETUP.md
```

## Features

- **Message Rate Tracking**: Tracks messages per user using DynamoDB
- **Threshold Detection**: Alerts admin when a user posts 5 messages within 3 minutes (configurable)
- **Admin Notifications**: Sends interactive alerts with action buttons
- **Message Management**: Allows admin to delete all flagged messages at once
- **User Deactivation**: Provides option to deactivate users who spam

## Architecture

The moderator consists of three main components:

1. **lambda_function.py**: Main handler for message events and interactive actions
2. **message_tracker.py**: DynamoDB-based message tracking and threshold detection
3. **slack_moderator.py**: Slack API integration for alerts and actions

## Environment Variables

- `SLACK_TOKEN`: Slack bot token for posting messages
- `USER_SLACK_TOKEN`: Slack user token with admin privileges for deleting messages and deactivating users
- `ADMIN_USER_ID`: Slack user ID of the admin who receives alerts (default: U01AXE0P5M3)
- `SLACK_TEAM_ID`: Slack team/workspace ID (required for user session invalidation)
- `MESSAGE_TRACKER_TABLE`: DynamoDB table name (default: slack-message-tracker)
- `MESSAGE_THRESHOLD`: Number of messages to trigger alert (default: 5)
- `TIME_WINDOW_SECONDS`: Time window in seconds (default: 180 = 3 minutes)
- `DYNAMODB_ENDPOINT`: Optional DynamoDB endpoint for LocalStack testing

## Deployment

### Package the Lambda

```bash
cd moderator
bash scripts/package.sh
```

### Deploy to AWS

```bash
bash scripts/deploy.sh
```

### Required AWS Resources

1. **Lambda Function**: `automator-message-moderator`
   - Runtime: Python 3.12
   - Handler: lambda_function.lambda_handler
   - Environment variables configured
   - IAM role with DynamoDB access

2. **DynamoDB Table**: The table is created automatically by the code if it doesn't exist
   - Table name: configured via `MESSAGE_TRACKER_TABLE` env var
   - Primary key: `user_id` (String)
   - Billing mode: Pay per request

3. **IAM Permissions**:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "dynamodb:PutItem",
           "dynamodb:GetItem",
           "dynamodb:DeleteItem",
           "dynamodb:CreateTable",
           "dynamodb:DescribeTable"
         ],
         "Resource": "arn:aws:dynamodb:*:*:table/slack-message-tracker"
       }
     ]
   }
   ```

## Slack Configuration

### Required Scopes

The bot requires the following OAuth scopes:

- `chat:write` - Post messages
- `users:read` - Read user information
- `admin.users.session:write` - Invalidate user sessions (recommended)
- OR `admin.users:write` - Deactivate users fully (Enterprise Grid only)
- `chat:write.admin` - Delete messages (requires user token)

### Event Subscriptions

Subscribe to the following Slack events:

- `message.channels` - Monitor public channel messages
- `message.groups` - Monitor private channel messages

### Interactive Components

Enable interactive components and set the request URL to your API Gateway endpoint that routes to this Lambda.

## Testing with LocalStack

### Start LocalStack

```bash
docker-compose up -d
```

### Run Tests

```bash
# Set environment for LocalStack
export DYNAMODB_ENDPOINT=http://localhost:4566

# Run tests
python -m pytest tests/test_message_tracker.py
python -m pytest tests/test_moderator_lambda.py
```

## Admin Alert Interface

When a user exceeds the message threshold, the admin receives an interactive message with:

- User information
- Preview of recent messages (up to 5)
- Three action buttons:
  1. **Delete All Messages**: Removes all tracked messages from the user
  2. **Deactivate User**: Deactivates the user's Slack account (requires confirmation)
  3. **Ignore**: Clears the alert and tracked messages without taking action

## Message Tracking

Messages are tracked in DynamoDB with the following structure:

```json
{
  "user_id": "U123456",
  "messages": [
    {
      "timestamp": 1234567890,
      "channel_id": "C123456",
      "message_ts": "1234567890.123456",
      "message_text": "Message preview..."
    }
  ],
  "last_updated": 1234567890
}
```

Messages older than the configured time window are automatically filtered out.
