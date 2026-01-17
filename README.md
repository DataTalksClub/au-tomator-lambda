It has three components:

* router - decides if it needs to invoke other functions based on event type
* automator - the main logic for handling reactions
* moderator - monitors message rates and alerts admin when thresholds are exceeded

The router and automator are split into two parts to work around Slack's 3 second timeout.

## Deployment

First, deploy the router:

```bash
cd router
bash publish.sh
```

Next, deploy the automator:

```bash
make deploy
```

Finally, deploy the moderator:

```bash
cd moderator
bash package.sh
bash deploy.sh
```

## Message Moderator

The moderator lambda monitors message rates and alerts administrators when users exceed configured thresholds. See [moderator/README.md](moderator/README.md) for detailed documentation.

**Key Features:**
- Tracks messages per user using DynamoDB
- Configurable threshold (default: 5 messages in 3 minutes)
- Interactive admin alerts with action buttons
- Bulk message deletion
- User deactivation capability
- LocalStack support for testing

## Application Configuration

This README provides an overview of the configuration file for our application, which manages various aspects of our Slack workspace and automated responses.


The configuration file is structured in YAML format and consists of the following main sections:

1. Admins
2. Channels
3. Reactions

### 1. Admins

This section lists the user IDs of administrators who have special privileges within the application.

```yaml
admins:
    - U01AXE0P5M3
```

### 2. Channels

This section maps channel IDs to their corresponding names. It helps identify specific channels for various operations.

```yaml
channels:
  C02R98X7DS9: "course-mlops-zoomcamp"
  C01FABYF2RG: "course-data-engineering"
  C0288NJ5XSA: "course-ml-zoomcamp"
  C06TEGTGM3J: "course-llm-zoomcamp"
```
### 3. Reactions

This section defines automated responses to specific reactions or triggers in the Slack workspace. Each reaction has a type, corresponding action, and may include placeholders.

#### Reaction Types:

1. `SLACK_POST`: Posts a message in the Slack channel
2. `DELETE_MESSAGE`: Removes a message and sends a notification to the user
3. `ASK_AI`: Utilizes an AI model to generate a response

#### Pre-defined Placeholders:

- `{user}`: Replaced with the username of the person who triggered the reaction
- `{channel}`: Replaced with the channel name where the reaction was triggered
- `{user_message}`: Replaced with the content of the user's message that triggered the reaction

#### Custom Placeholders:

Some reactions use custom placeholders, such as `{link}` in the `faq` reaction. These are defined in the `placeholders` section of each reaction.

#### Default Placeholder Behavior:

For reactions with channel-specific placeholders (like `{link}` in the `faq` reaction):

- If a matching channel is found, the corresponding value is used.
- If no matching channel is found, but a `default` value is set, the default value is used.
- If no matching channel is found and no default value is set, no action is taken.

#### Detailed Reaction Descriptions:

1. `dont-ask-to-ask-just-ask`:
   - Type: `SLACK_POST`
   - Action: Posts a message encouraging users to ask their questions directly

2. `thread`:
   - Type: `REMOVE_BROADCAST_AND_POST`
   - Action: Reminds users to use threads for organized discussions
   - Special behavior: If the message is a thread reply that was "also sent to channel" (broadcasted), it removes the message from the channel view while keeping it in the thread, then posts the reminder message

3. `faq`:
   - Type: `SLACK_POST`
   - Action: Provides links to course-specific FAQs
   - Placeholders: 
     - `{link}`: Channel-specific FAQ links
   - Default behavior: Uses a default link if the channel doesn't match

4. `error-log-to-thread-please`:
   - Type: `SLACK_POST`
   - Action: Instructs users on how to properly share error logs
   - Placeholders:
     - `{link}`: Channel-specific guidelines for sharing error logs
   - Default behavior: Uses a default link if the channel doesn't match

5. `no-screenshot`:
   - Type: `SLACK_POST`
   - Action: Advises against posting screenshots of code
   - Placeholders:
     - `{link}`: Channel-specific guidelines for sharing code
   - Default behavior: Uses a default link if the channel doesn't match

6. `shameless-rules`:
   - Type: `DELETE_MESSAGE`
   - Action: Enforces rules for shameless promotion channels
   - Uses pre-defined placeholders: `{user}`, `{channel}`, `{user_message}`

7. `jobs-rules`:
   - Type: `DELETE_MESSAGE`
   - Action: Enforces rules for job postings
   - Uses pre-defined placeholders: `{user}`, `{channel}`, `{user_message}`

8. `ask-ai`:
   - Type: `ASK_AI`
   - Action: Utilizes an AI model (`llama3-70b-8192`) to answer user questions
   - Model: `llama3-70b-8192`
   - Prompt template: Includes the user's message
   - Answer template: Formats the AI's response for posting in Slack

## Usage

This configuration file is used by the application to manage automated responses and actions within the Slack workspace. It helps maintain community guidelines, provides helpful resources, and ensures a smooth experience for all users in the various course-related channels.

To modify the configuration, edit the YAML file directly. Ensure that you follow the existing structure and formatting to maintain compatibility with the application.