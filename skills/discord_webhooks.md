# Skill: Discord Webhook Management

## Agent: architect
## Risk: medium
## Category: webhooks

### Tools

#### create_webhook
- Description: Create a webhook for a channel (for automated messages/integrations).
- Parameters:
  - guild_id (integer, required): Target guild ID
  - channel_name (string, required): Channel to attach webhook to
  - webhook_name (string, required): Display name for the webhook
  - avatar_url (string): Avatar image URL for the webhook
- Risk: medium
- Requires Approval: no

#### delete_webhook
- Description: Delete a webhook from a channel.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - channel_name (string, required): Channel the webhook is in
  - webhook_name (string, required): Webhook name to delete
- Risk: medium
- Requires Approval: no

#### send_webhook_message
- Description: Send a message through a webhook (custom username/avatar).
- Parameters:
  - webhook_url (string, required): Full webhook URL
  - content (string, required): Message text
  - username (string): Override display name
  - avatar_url (string): Override avatar
  - embed (object): Discord embed object
- Risk: medium
- Requires Approval: no

#### list_webhooks
- Description: List all webhooks in a channel or server.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - channel_name (string): Filter to specific channel (omit for all)
- Risk: low
- Requires Approval: no
