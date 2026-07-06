# backup

## Tools

### export_structure
- description: Export the complete guild structure (channels, roles, categories, permissions) as JSON
- risk: low
- agent: fast_track
- parameters:
  - guild_id (int, required): Target guild ID
  - include_permissions (bool, optional): Whether to include channel permission overwrites (default true)
  - include_webhooks (bool, optional): Whether to include webhook configurations (default false)

### import_structure
- description: Import a previously exported guild structure and recreate channels, roles, and categories
- risk: critical
- agent: admin
- parameters:
  - guild_id (int, required): Target guild ID
  - structure (dict, required): Previously exported structure JSON object
  - overwrite (bool, optional): Whether to delete existing structure before import (default false)
  - dry_run (bool, optional): Preview changes without applying them (default true)
  - reason (str, optional): Audit log reason
