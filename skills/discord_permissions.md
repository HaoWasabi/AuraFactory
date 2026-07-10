# discord.permissions — Knowledge for LLM

## Available Actions
- set_channel_perms, set_role_perms, sync

## Key Concepts

### Channel Permissions vs Role Permissions
- **Role permissions** (set_role_perms): Base guild-wide permissions for a role. Apply everywhere.
- **Channel permissions** (set_channel_perms): Override base permissions for a specific channel. Can allow OR deny.

### When to Use Which
| Goal | Action |
|------|--------|
| "Make Moderator role able to kick/ban everywhere" | `set_role_perms(role_id, kick_members=true, ban_members=true)` |
| "Hide #staff-chat from @everyone" | `set_channel_perms(channel_id, target_id=EVERYONE_ROLE_ID, target_type="role", view_channel=false)` |
| "Let VIP role see #staff-chat" | `set_channel_perms(channel_id, target_id=VIP_ROLE_ID, target_type="role", view_channel=true)` |
| "Reset channel perms to match category" | `sync(channel_id)` |

### Permission Override Values
- `true` = explicitly ALLOW (overrides role deny)
- `false` = explicitly DENY (overrides role allow)
- Not provided = inherit from role/category

### Important Permission Names
**Dangerous (high-risk):**
- administrator — full access, bypasses all checks
- manage_guild — server settings
- manage_roles — can edit roles below own
- ban_members, kick_members

**Common:**
- view_channel, send_messages, read_message_history
- connect, speak (voice)
- manage_messages (delete/pin others' messages)
- manage_channels, manage_threads
- attach_files, embed_links, add_reactions
- mention_everyone

### Common Patterns
1. **Private channel setup**:
   - set_channel_perms(channel_id, target=@everyone, view_channel=false)
   - set_channel_perms(channel_id, target=STAFF_ROLE, view_channel=true, send_messages=true)

2. **Read-only announcements**:
   - set_channel_perms(channel_id, target=@everyone, send_messages=false)
   - set_channel_perms(channel_id, target=ADMIN_ROLE, send_messages=true)

3. **Mute a role in a channel**:
   - set_channel_perms(channel_id, target=MUTED_ROLE, send_messages=false, add_reactions=false)
