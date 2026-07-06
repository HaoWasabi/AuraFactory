# Skill: Discord Server Backup & Templates

## Agent: architect
## Risk: medium
## Category: backup

### Tools

#### backup_server
- Description: Create a full backup of server structure (channels, roles, permissions, settings).
- Parameters:
  - guild_id (integer, required): Target guild ID
  - include_messages (boolean, default: false): Include recent messages (slower)
  - format (string, enum: json|yaml, default: json): Output format
- Risk: medium
- Requires Approval: no

#### restore_server
- Description: Restore server structure from a backup file. Creates missing channels/roles.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - backup_data (object, required): Backup data to restore from
  - overwrite (boolean, default: false): Overwrite existing items
- Risk: high
- Requires Approval: yes

#### apply_template
- Description: Apply a pre-built server template (gaming, study, startup).
- Parameters:
  - guild_id (integer, required): Target guild ID
  - template_name (string, required, enum: gaming_community|study_group|startup_team): Template to apply
  - clear_existing (boolean, default: false): Remove existing channels first
- Risk: high
- Requires Approval: yes
- Examples:
  - Input: {"guild_id": 123456, "template_name": "startup_team", "clear_existing": false}
  - Output: {"created_categories": 4, "created_channels": 12, "created_roles": 5}

#### list_templates
- Description: List available server templates with descriptions.
- Parameters:
  - guild_id (integer, required): Target guild ID
- Risk: low
- Requires Approval: no
