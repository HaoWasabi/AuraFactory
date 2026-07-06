# webhooks

## Tools

### create
- description: Create a new webhook for a channel
- risk: medium
- agent: assistant
- parameters:
  - guild_id (int, required): Target guild ID
  - channel_id (int, required): Channel to create webhook in
  - name (str, required): Webhook display name
  - avatar_url (str, optional): URL for webhook avatar image
  - reason (str, optional): Audit log reason

### delete
- description: Delete an existing webhook
- risk: high
- agent: admin
- parameters:
  - guild_id (int, required): Target guild ID
  - webhook_id (int, required): Webhook ID to delete
  - reason (str, optional): Audit log reason

### list
- description: List all webhooks in the guild or a specific channel
- risk: low
- agent: fast_track
- parameters:
  - guild_id (int, required): Target guild ID
  - channel_id (int, optional): Filter by channel ID
