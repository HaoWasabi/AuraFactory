# channels

## Tools

### create
- description: Create a new text or voice channel in the guild
- risk: medium
- parameters:
  - guild_id (int, required): Target guild ID
  - name (str, required): Channel name (auto-slugified)
  - channel_type (str, required): Channel type — text, voice, stage, forum
  - category_id (int, optional): Parent category ID to nest under
  - topic (str, optional): Channel topic (text channels only)
  - nsfw (bool, optional): Whether the channel is NSFW
  - slowmode (int, optional): Slowmode delay in seconds (0-21600)
  - position (int, optional): Channel position in the list
  - reason (str, optional): Audit log reason

### delete
- description: Delete an existing channel from the guild
- risk: high
- parameters:
  - guild_id (int, required): Target guild ID
  - channel_id (int, required): Channel ID to delete
  - reason (str, optional): Audit log reason

### rename
- description: Rename an existing channel
- risk: medium
- parameters:
  - guild_id (int, required): Target guild ID
  - channel_id (int, required): Channel ID to rename
  - name (str, required): New channel name
  - reason (str, optional): Audit log reason

### move
- description: Move a channel to a different category or position
- risk: medium
- parameters:
  - guild_id (int, required): Target guild ID
  - channel_id (int, required): Channel ID to move
  - category_id (int, optional): New parent category ID (null to remove from category)
  - position (int, optional): New position within category
  - reason (str, optional): Audit log reason

### edit
- description: Edit channel properties (topic, slowmode, nsfw, bitrate, user_limit)
- risk: medium
- parameters:
  - guild_id (int, required): Target guild ID
  - channel_id (int, required): Channel ID to edit
  - topic (str, optional): New channel topic
  - nsfw (bool, optional): NSFW flag
  - slowmode (int, optional): Slowmode delay in seconds
  - bitrate (int, optional): Voice channel bitrate
  - user_limit (int, optional): Voice channel user limit
  - reason (str, optional): Audit log reason

### list
- description: List all channels in the guild or a specific category
- risk: low
- parameters:
  - guild_id (int, required): Target guild ID
  - category_id (int, optional): Filter by parent category ID
  - channel_type (str, optional): Filter by type (text, voice, stage, forum)
