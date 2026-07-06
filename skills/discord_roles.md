# roles

## Tools

### create
- description: Create a new role in the guild with specified properties
- risk: medium
- agent: assistant
- parameters:
  - guild_id (int, required): Target guild ID
  - name (str, required): Role name
  - color (int, optional): Role color as integer (hex)
  - hoist (bool, optional): Whether to display role separately in member list
  - mentionable (bool, optional): Whether the role can be mentioned
  - permissions (int, optional): Permission bitfield value
  - position (int, optional): Role position in hierarchy
  - reason (str, optional): Audit log reason

### delete
- description: Delete an existing role from the guild
- risk: high
- agent: admin
- parameters:
  - guild_id (int, required): Target guild ID
  - role_id (int, required): Role ID to delete
  - reason (str, optional): Audit log reason

### rename
- description: Rename an existing role
- risk: medium
- agent: assistant
- parameters:
  - guild_id (int, required): Target guild ID
  - role_id (int, required): Role ID to rename
  - name (str, required): New role name
  - reason (str, optional): Audit log reason

### set_permissions
- description: Set the permission bitfield for a role
- risk: high
- agent: admin
- parameters:
  - guild_id (int, required): Target guild ID
  - role_id (int, required): Role ID to modify
  - permissions (int, required): New permission bitfield value
  - reason (str, optional): Audit log reason

### assign
- description: Assign a role to a guild member
- risk: medium
- agent: assistant
- parameters:
  - guild_id (int, required): Target guild ID
  - member_id (int, required): Member user ID
  - role_id (int, required): Role ID to assign
  - reason (str, optional): Audit log reason

### remove
- description: Remove a role from a guild member
- risk: medium
- agent: assistant
- parameters:
  - guild_id (int, required): Target guild ID
  - member_id (int, required): Member user ID
  - role_id (int, required): Role ID to remove
  - reason (str, optional): Audit log reason
