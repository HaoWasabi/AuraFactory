# permissions

## Tools

### set_channel_perms
- description: Set permission overwrites for a role or member on a specific channel
- risk: high
- agent: admin
- parameters:
  - guild_id (int, required): Target guild ID
  - channel_id (int, required): Channel to set permissions on
  - target_id (int, required): Role or member ID to apply overwrite to
  - target_type (str, required): Target type — role or member
  - allow (int, required): Permission bitfield to explicitly allow
  - deny (int, required): Permission bitfield to explicitly deny
  - reason (str, optional): Audit log reason

### set_role_perms
- description: Set the base permission bitfield for a guild role
- risk: high
- agent: admin
- parameters:
  - guild_id (int, required): Target guild ID
  - role_id (int, required): Role ID to modify
  - permissions (int, required): New permission bitfield value
  - reason (str, optional): Audit log reason

### sync
- description: Sync channel permissions with its parent category
- risk: medium
- agent: assistant
- parameters:
  - guild_id (int, required): Target guild ID
  - channel_id (int, required): Channel to sync permissions for
  - reason (str, optional): Audit log reason
