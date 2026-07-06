# Skill: Discord Channel Management

## Agent: architect
## Risk: medium
## Category: channels

### Tools

#### create_channel
- Description: Create a new channel in the Discord server.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - name (string, required): Channel name (auto-formatted to lowercase-hyphenated)
  - channel_type (string, enum: text|voice|forum|stage|announcement, default: text): Channel type
  - category (string): Category name to place the channel under
  - topic (string): Channel topic/description
  - is_private (boolean, default: false): Whether channel is private
  - slowmode (integer, default: 0): Slowmode delay in seconds (0-21600)
- Risk: medium
- Requires Approval: no
- Examples:
  - Input: {"guild_id": 123456, "name": "general", "channel_type": "text", "category": "THÔNG TIN"}
  - Output: {"channel_id": 789012, "name": "general", "type": "text"}

#### delete_channel
- Description: Delete a channel — THIS CANNOT BE UNDONE. All messages will be lost.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - channel_name (string, required): Name or ID of channel to delete
  - reason (string, default: AI Agent Request): Audit log reason
- Risk: high
- Requires Approval: yes

#### edit_channel
- Description: Modify channel settings (name, topic, slowmode, etc.).
- Parameters:
  - guild_id (integer, required): Target guild ID
  - channel_name (string, required): Current channel name
  - new_name (string): New name for the channel
  - new_topic (string): New topic/description
  - slowmode (integer): New slowmode delay in seconds
  - nsfw (boolean): Mark as NSFW
- Risk: medium
- Requires Approval: no

#### list_channels
- Description: List all channels in the server, optionally filtered by type.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - channel_type (string, enum: text|voice|forum|stage|all, default: all): Filter by type
  - category (string): Filter by category name
- Risk: low
- Requires Approval: no

#### move_channel
- Description: Move a channel to a different category.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - channel_name (string, required): Channel to move
  - target_category (string, required): Destination category name
  - position (integer): Position within category
- Risk: medium
- Requires Approval: no
