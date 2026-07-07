# webhooks

## Tools

### create
- description: Create a new webhook for a channel
- risk: medium
- parameters:
  - guild_id (int, required): Target guild ID
  - channel_id (int, required): Channel to create webhook in
  - name (str, required): Webhook display name
  - avatar_url (str, optional): URL for webhook avatar image
  - reason (str, optional): Audit log reason

### delete
- description: Delete an existing webhook
- risk: high
- parameters:
  - guild_id (int, required): Target guild ID
  - webhook_id (int, required): Webhook ID to delete
  - reason (str, optional): Audit log reason

### list
- description: List all webhooks in the guild or a specific channel
- risk: low
- parameters:
  - guild_id (int, required): Target guild ID
  - channel_id (int, optional): Filter by channel ID
