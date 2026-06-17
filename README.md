# AuTomator

A Slack moderation bot that runs on AWS Lambda. It lets you moderate from your phone—no laptop, no scanning every channel manually. I built it in June 2022 and have kept adding features as new needs came up.

## How the AuTomator Works

The backend is split into **three Lambdas**, each with a clear responsibility.

### 1. Router — Routes Slack events to the right Lambda

Everything from Slack goes through the router: messages, emoji reactions, and button clicks.

Its only job is to look at the incoming event and quickly decide where it should go next:

| Event | Routed to |
|-------|-----------|
| **Reaction added by admin** | Automator |
| **App mention** | Automator / FAQ Assistant |
| **Message event** | Disabled for now |
| **Button click** (e.g. from an alert) | Moderator |

The router and automator are separate on purpose: Slack expects a response within about 3 seconds. The router responds immediately and invokes the automator (or moderator) asynchronously, so longer work doesn’t time out.

### 2. Automator — Acts based on emoji reactions by the admin and FAQ mentions

This is for fast reaction on spam and other rule violations.

- The bot has a list of **specified emojis** and the **actions** that go with each.
- When you react to any message with one of those emojis, the automator looks up the action and runs it. Actions can be:
  - **Posting a reply** in the thread (e.g. FAQ link, “use threads” reminder).
  - **Deleting the message** and sending a DM to the author explaining why (e.g. rule violation).
  - **Asking an AI** to generate an answer and posting it in the thread (e.g. `:ask-ai:`).
- When anyone tags the bot, the automator can call the Cloudflare FAQ assistant and post the answer in the thread.

Examples:

- **:ask-ai:** — Automator replies in the thread with an AI-generated answer.
- **:rule-book:** (or similar) — Automator deletes the message and DMs the author that it violated community rules and was deleted.

The automator can also send a relevant reply to the author of the message you reacted to, so they get clear feedback.

### 3. Moderator — Watches message activity and helps you react quickly

The moderator **does not** decide what is spam by itself. It:

- Keeps track of how often people post (e.g. messages per user in a time window).
- Notices patterns like “too many messages too quickly.”
- When that happens, **alerts an admin** and provides **buttons** to act immediately.

Those buttons let you **delete recent messages**, **deactivate a user**, or **ignore** the alert—all from Slack, including on your phone. So you get early signals and can intervene quickly without opening a laptop.

For more on the moderator (DynamoDB, thresholds, LocalStack, etc.), see [moderator/README.md](moderator/README.md).

---

## Deployment

Deploy in this order:

**1. Router**

```bash
cd router
bash publish.sh
```

The router Lambda function name is `slack-test`. The separate GitHub Actions workflow
`.github/workflows/deploy-router.yml` deploys this Lambda after tests pass on `main`,
or manually via workflow dispatch. If the Lambda is renamed later, set the repository
variable `ROUTER_FUNCTION_NAME`; otherwise it defaults to `slack-test`.

The AWS credentials used by GitHub Actions need `lambda:UpdateFunctionCode`,
`lambda:GetFunction`, and `lambda:GetFunctionConfiguration` for `slack-test`.

**2. Automator**

```bash
make deploy
```

**3. Moderator**

```bash
cd moderator
bash package.sh
bash deploy.sh
```

---

## Message Moderator (reference)

- Tracks messages per user using **DynamoDB**.
- Configurable threshold (default: 5 messages in 3 minutes).
- Interactive admin alerts with action buttons.
- Bulk message deletion and user deactivation.
- LocalStack support for testing.

See [moderator/README.md](moderator/README.md) and [moderator/SLACK_SETUP.md](moderator/SLACK_SETUP.md) for setup and details.

---

## Application Configuration

Behavior is driven by **`automator/config.yaml`**, which is in YAML and has three main sections.

### 1. Admins

Slack user IDs of people who can trigger reaction-based actions (e.g. who can use the automator emojis).

```yaml
admins:
  - U01AXE0P5M3
```

### 2. Channels

Maps Slack channel IDs to human-readable names (used for channel-specific messages and placeholders).

```yaml
channels:
  C02R98X7DS9: "course-mlops-zoomcamp"
  C01FABYF2RG: "course-data-engineering"
  C0288NJ5XSA: "course-ml-zoomcamp"
  C06TEGTGM3J: "course-llm-zoomcamp"
```

### 3. Reactions

Each entry defines an emoji (reaction name) and what the automator should do when an admin uses it.

- **Reaction** — The emoji/short name (e.g. `thread`, `faq`, `ask-ai`).
- **Type (or types)** — The kind of action; you can list multiple and they run in sequence.
- **Message / placeholders** — Text to post or send in DMs, with optional placeholders.

#### Reaction types

| Type | What it does |
|------|------------------|
| `SLACK_POST` | Posts a message in the thread (e.g. reminder, link). |
| `DELETE_MESSAGE` | Deletes the message and sends a DM to the author (e.g. rule violation). |
| `ASK_AI` | Calls an AI model, then posts the reply in the thread. |
| `FAQ_ASSISTANT` | Calls the Cloudflare FAQ assistant, then posts the reply in the thread. |
| `REMOVE_BROADCAST` | Removes a “also sent to channel” thread reply from the channel (keeps it in the thread). |
| `REPOST_TO_THREAD_AND_DELETE` | Reposts the message to the thread with a custom message, then deletes it from the channel. |

#### Multiple handlers

Use `types` (a list) to run several actions for one reaction:

```yaml
- reaction: thread
  types:
    - REMOVE_BROADCAST   # First: remove if broadcasted
    - SLACK_POST        # Then: post reminder
  message: "Please use threads..."
```

#### Placeholders

- **Pre-defined:** `{user}`, `{channel}`, `{user_message}` (author, channel, message text).
- **Custom:** e.g. `{link}` — defined under `placeholders` per reaction, often with channel-specific or `default` values.

If a placeholder is channel-specific and the channel isn’t in the map, the `default` value is used when set; otherwise that reaction is skipped for that channel.

#### Example reactions (from config)

| Reaction | Type | Purpose |
|----------|------|---------|
| `dont-ask-to-ask-just-ask` | SLACK_POST | Encourage asking questions directly. |
| `thread` | REMOVE_BROADCAST + SLACK_POST | Remove broadcasted reply, post thread reminder. |
| `faq` | FAQ_ASSISTANT | Answer the reacted message with the Cloudflare FAQ assistant. |
| `error-log-to-thread-please` | SLACK_POST | How to share error logs. |
| `error-log-to-thread-and-delete` | REPOST_TO_THREAD_AND_DELETE | Move error log to thread, delete from channel. |
| `no-screenshot` | SLACK_POST | Advise against code screenshots; link to guidelines. |
| `shameless-rules` | DELETE_MESSAGE | Enforce shameless-promo rules; DM author. |
| `jobs-rules` | DELETE_MESSAGE | Enforce job-posting rules; DM author. |
| `ask-ai` | ASK_AI | Generate and post an AI reply in the thread. |

To change behavior, edit `automator/config.yaml` and keep the same structure so the application stays compatible.

## FAQ Assistant Integration

Set `FAQ_ASSISTANT_URL` on the automator Lambda:

```bash
FAQ_ASSISTANT_URL=https://<cloudflare-worker>/ask
```

Set the same shared secret on the automator Lambda and the Cloudflare Worker:

```bash
FAQ_ASSISTANT_SHARED_SECRET=...
```

Any user can tag the bot and the router forwards the event to the automator. If `FAQ_ASSISTANT_URL` is unset on the automator Lambda, the automator skips the FAQ assistant request. Reaction events are still forwarded only when the reacting user is an admin.

The automator sends the shared secret as `x-faq-assistant-secret`; the Cloudflare Worker rejects `/ask` calls when its own `FAQ_ASSISTANT_SHARED_SECRET` is set and the header is missing or different.
