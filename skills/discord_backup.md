# discord.backup — Knowledge for LLM

## Available Actions
- export, restore

## Key Rules

### export
Creates a JSON snapshot of the entire server structure.
- No params needed (uses guild from context)
- Returns: categories, channels, roles, permissions, server settings
- Does NOT export: messages, member list, files, emoji images

### restore
Recreates server structure from a backup JSON.
- `backup_data`: the JSON export object
- **HIGH RISK**: Creates categories, channels, roles from scratch
- Does NOT delete existing things first — may create duplicates
- Role hierarchy may not match exactly (positions shift)

### Limitations
- Backup is structural only (no message history)
- Webhooks are NOT backed up (contain secrets)
- Custom emoji images are NOT included (only names/IDs)
- Member role assignments are NOT included

### Common Patterns
1. **Before major restructure**: export → make changes → if disaster, refer to export
2. **Clone server template**: export from template server → restore into new server
3. **Migration**: export from old bot → manually adjust → restore

### Safety
- restore is CRITICAL risk — always requires approval
- Suggest exporting BEFORE any bulk delete operations
