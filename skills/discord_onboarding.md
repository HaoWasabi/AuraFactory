# onboarding

## Tools

### setup_welcome
- description: Configure the welcome system for new members (welcome channel, message template)
- risk: medium
- agent: assistant
- parameters:
  - guild_id (int, required): Target guild ID
  - channel_id (int, required): Channel to send welcome messages in
  - message_template (str, required): Welcome message template (supports {user}, {guild}, {member_count} placeholders)
  - enabled (bool, optional): Whether welcome messages are enabled (default true)

### create_dm_template
- description: Create or update a DM template sent to new members on join
- risk: medium
- agent: assistant
- parameters:
  - guild_id (int, required): Target guild ID
  - template_name (str, required): Template identifier name
  - content (str, required): DM message content (supports {user}, {guild} placeholders)
  - embed_title (str, optional): Optional embed title
  - embed_description (str, optional): Optional embed description
  - embed_color (int, optional): Embed color as integer

### send_dm
- description: Send a direct message to a guild member using a template or custom content
- risk: medium
- agent: assistant
- parameters:
  - guild_id (int, required): Target guild ID
  - member_id (int, required): Member user ID to DM
  - template_name (str, optional): Template name to use (mutually exclusive with content)
  - content (str, optional): Custom message content (mutually exclusive with template_name)
