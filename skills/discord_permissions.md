# Skill: Discord Permission Management

## Agent: architect
## Risk: medium
## Category: permissions

### Tools

#### set_channel_permission
- Description: Set permission overwrites for a role/member on a specific channel.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - channel_name (string, required): Channel to modify
  - target_name (string, required): Role name or user mention to set permissions for
  - target_type (string, enum: role|member, default: role): Whether target is a role or member
  - allow (array): Permissions to explicitly allow
  - deny (array): Permissions to explicitly deny
- Risk: medium
- Requires Approval: no
- Examples:
  - Input: {"guild_id": 123456, "channel_name": "admin-only", "target_name": "Member", "target_type": "role", "deny": ["view_channel"]}
  - Output: {"success": true, "channel": "admin-only", "target": "Member"}

#### sync_permissions
- Description: Sync channel permissions with its parent category.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - channel_name (string, required): Channel to sync
- Risk: medium
- Requires Approval: no

#### get_channel_permissions
- Description: View current permission overwrites for a channel.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - channel_name (string, required): Channel to inspect
- Risk: low
- Requires Approval: no
