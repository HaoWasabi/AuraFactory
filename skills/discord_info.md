# info

## Tools

### get_guild_info
- description: Get comprehensive guild information including name, owner, member count, features, and verification level
- risk: low
- agent: fast_track
- parameters:
  - guild_id (int, required): Target guild ID

### list_channels
- description: List all channels in the guild with type, category, topic, and position
- risk: low
- agent: fast_track
- parameters:
  - guild_id (int, required): Target guild ID
  - channel_type (str, optional): Filter by type (text, voice, stage, forum)
  - category_id (int, optional): Filter by parent category

### list_roles
- description: List all roles in the guild with color, permissions, and position
- risk: low
- agent: fast_track
- parameters:
  - guild_id (int, required): Target guild ID
  - include_permissions (bool, optional): Whether to include permission bitfield details (default false)

### list_categories
- description: List all categories in the guild with their child channels
- risk: low
- agent: fast_track
- parameters:
  - guild_id (int, required): Target guild ID

### get_channel_info
- description: Get detailed information about a specific channel including topic, permissions, and settings
- risk: low
- agent: fast_track
- parameters:
  - guild_id (int, required): Target guild ID
  - channel_id (int, required): Channel ID to get info for
