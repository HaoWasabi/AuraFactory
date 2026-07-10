# discord.roles — Knowledge for LLM

## Available Actions
- create, bulk_create, rename, modify, delete, assign, remove, batch_assign, clone, set_position, list, get_info

## Key Rules

### Role Hierarchy (CRITICAL)
- Bot can only modify roles BELOW its own highest role
- Cannot assign a role higher than bot's role to anyone
- Position 0 = bottom (@everyone), higher = more authority
- When creating: new roles start at position 1 (just above @everyone)

### Action Selection Guide
| Need | Use | NOT |
|------|-----|-----|
| Create 1 role | `create` | - |
| Create 3+ roles at once | `bulk_create` | multiple `create` calls |
| Change name only | `rename` | `modify` (overkill) |
| Change name + color + perms | `modify` | separate calls |
| Copy a role's settings | `clone` | manual create + set same perms |
| Assign role to 1 member | `assign` | `batch_assign` |
| Assign role to 5+ members | `batch_assign` | multiple `assign` calls |

### Parameters by Action
- `create`: name, color, hoist, mentionable, permissions, position, reason
- `bulk_create`: roles (list of {name, color?, hoist?, mentionable?, permissions?}), reason
- `rename`: role_id, name, reason
- `modify`: role_id + any of: name, color, hoist, mentionable, permissions, position, reason
- `assign`: role_id, member_id
- `remove`: role_id, member_id
- `batch_assign`: role_id, member_ids (list), action ("add" or "remove")
- `clone`: role_id, new_name
- `set_position`: role_id, position

### Color Format
- Hex string: "#ff0000" or "ff0000"
- Integer: 16711680
- Common: red=#e74c3c, blue=#3498db, green=#2ecc71, gold=#f1c40f, purple=#9b59b6

### Permission Dict Format
```json
{"manage_messages": true, "kick_members": true, "ban_members": false}
```
Only include permissions you want to SET. Unmentioned perms stay unchanged (modify uses merge).

### Common Patterns
1. **Server setup**: bulk_create all roles → set_position for hierarchy → assign to members
2. **Mod role**: create with permissions {manage_messages, kick_members, moderate_members}
3. **Color role**: create with color + hoist=true, no special permissions
4. **VIP from template**: clone existing role → rename
