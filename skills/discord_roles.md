# Skill: Discord Role Management

## Agent: architect
## Risk: medium
## Category: roles

### Tools

#### create_role
- Description: Create a new role with specified permissions and appearance.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - name (string, required): Role name
  - color (string): Hex color code (e.g. #FF5733)
  - permissions (array): List of permission names to grant
  - mentionable (boolean, default: false): Allow anyone to @mention this role
  - hoist (boolean, default: false): Show role separately in member sidebar
  - position (integer): Role hierarchy position
- Risk: medium
- Requires Approval: no
- Examples:
  - Input: {"guild_id": 123456, "name": "Moderator", "color": "#3498DB", "permissions": ["kick_members", "ban_members"], "hoist": true}
  - Output: {"role_id": 654321, "name": "Moderator", "color": "#3498DB"}

#### delete_role
- Description: Delete a role — all members will lose this role immediately.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - role_name (string, required): Role name to delete
  - reason (string, default: AI Agent Request): Audit log reason
- Risk: high
- Requires Approval: yes

#### assign_role
- Description: Assign a role to a member.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - user_id (integer, required): Target member's user ID
  - role_name (string, required): Role name to assign
- Risk: medium
- Requires Approval: no

#### remove_role
- Description: Remove a role from a member.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - user_id (integer, required): Target member's user ID
  - role_name (string, required): Role name to remove
- Risk: medium
- Requires Approval: no

#### list_roles
- Description: List all roles in the server with member counts.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - include_permissions (boolean, default: false): Include permission details
- Risk: low
- Requires Approval: no
