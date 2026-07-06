# Skill: Discord Server Info

## Agent: assistant
## Risk: low
## Category: info

### Tools

#### get_guild_info
- Description: Get comprehensive server information (name, members, boosts, features).
- Parameters:
  - guild_id (integer, required): Target guild ID
- Risk: low
- Requires Approval: no

#### server_snapshot
- Description: Get a full snapshot of server structure (categories, channels, roles, member count).
- Parameters:
  - guild_id (integer, required): Target guild ID
  - include_permissions (boolean, default: false): Include permission details per channel
- Risk: low
- Requires Approval: no

#### list_members
- Description: List server members with their roles.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - limit (integer, default: 100): Max members to return
  - role_filter (string): Only show members with this role
- Risk: low
- Requires Approval: no

#### list_invites
- Description: List all active invite links.
- Parameters:
  - guild_id (integer, required): Target guild ID
- Risk: low
- Requires Approval: no

#### list_emojis
- Description: List all custom emojis in the server.
- Parameters:
  - guild_id (integer, required): Target guild ID
- Risk: low
- Requires Approval: no

#### list_threads
- Description: List active and archived threads.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - include_archived (boolean, default: false): Include archived threads
- Risk: low
- Requires Approval: no
