# discord.onboarding — Knowledge for LLM

## Available Actions
- get, setup, setup_welcome, send_dm

## Key Rules

### Onboarding (Discord's built-in feature)
Requires COMMUNITY feature enabled. Presents new members with customization prompts.

### setup
Params:
- `prompts`: list of question prompts for new members
- `default_channel_ids`: channels shown to ALL new members by default
- `enabled`: true/false

Prompt format:
```json
{
  "type": 0,
  "title": "What are you interested in?",
  "options": [
    {
      "title": "Gaming",
      "description": "Access gaming channels",
      "channel_ids": ["123456"],
      "role_ids": ["789012"]
    }
  ]
}
```

### setup_welcome
Configures the system channel for join notifications.
- `channel_id`: text channel for join messages
- `suppress_join_notifications`: false = show "X joined the server" messages

### send_dm
Send a DM to a specific member (e.g., welcome message, warning).
- `member_id`: target member
- `message`: content (max 2000 chars)
- Note: Will fail if member has DMs disabled — catch gracefully

### Common Patterns
1. **Welcome flow**: setup_welcome(channel_id) → send_dm to specific new members
2. **Full onboarding**: set_community(enable=true) → setup(prompts, default_channel_ids, enabled=true)
3. **Custom welcome DM**: On member_join event → send_dm with personalized greeting
