# discord.webhooks — Knowledge for LLM

## Available Actions
- create, delete, list

## Key Rules

### create
- `channel_id`: target text channel
- `name`: webhook display name (1-80 chars)
- `avatar_url`: optional avatar image URL
- Returns: webhook URL (secret — should be stored securely)

### delete
- `webhook_id`: ID of webhook to delete

### list
- Optional `channel_id` filter
- Returns all webhooks the bot can see

### Use Cases
- Integration with external services (GitHub, Trello, etc.)
- Custom notification bots with different names/avatars
- Automated posting (announcements, RSS feeds)

### Limits
- Max 15 webhooks per channel
- Webhook names cannot be "clyde" (reserved by Discord)
- Bot needs manage_webhooks permission

### Security Note
- Webhook URLs are sensitive — anyone with the URL can post
- Never expose webhook URLs in public channels
- Suggest creating webhooks in admin-only channels
