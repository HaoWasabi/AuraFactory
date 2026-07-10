# discord.channels — Knowledge for LLM

## Available Actions
- create, rename, edit, delete, move, list

## Key Rules

### Channel Types & Required Features
| Type | Requires COMMUNITY? | Notes |
|------|---------------------|-------|
| text | No | Default type. Supports topic, slowmode, nsfw |
| voice | No | Supports bitrate (8000-384000), user_limit (0-99) |
| stage | **Yes** | Like voice + audience. Needs topic for stage instance |
| forum | **Yes** | Thread-based. Supports default_auto_archive_duration |
| news/announcement | **Yes** | Cross-server publishing. Max 10 per guild |

### Parameter Interactions
- `is_private=true` → MUST provide `allowed_role_ids` or `allowed_user_ids` (otherwise nobody can see it)
- `category_id` → channel inherits category permissions (unless is_private overrides)
- `slowmode_delay` → only text/forum channels (0-21600 seconds)
- `bitrate` → only voice/stage (default 64000, max depends on boost tier)
- `user_limit` → only voice (0 = unlimited, max 99)

### Naming Rules
- Discord auto-converts names: spaces → hyphens, uppercase → lowercase
- Max 100 chars, min 1 char
- Forum channels can have emoji in name

### Common Patterns
1. **Private channel**: `create_channel(name="staff-chat", type="text", is_private=true, allowed_role_ids=[MOD_ROLE_ID])`
2. **Category + channels**: create category first → use its ID as `category_id` in channel creation
3. **News channel**: requires COMMUNITY → suggest `set_community(enable=true)` first if not enabled

### Error Prevention
- If COMMUNITY not enabled and user wants stage/news/forum → suggest enabling Community first
- Don't create channels with duplicate names in same category (Discord allows it but confuses users)
- Voice channels don't support `topic` param — it will be silently dropped
