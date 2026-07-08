# AuraFactory Discord Connectors — SPEC v2

> Canonical spec for the Discord connector tool layer.
> All connector implementations MUST conform to this document.

---

## Architecture

### Location
Tools live in `app/connectors/discord/` — each file is a connector class
that exposes async methods (actions) called via MCP protocol.

### Foundation modules (private, prefixed with `_`)
- `_validation.py` — PARAM_WHITELIST + validate_kwargs() + precondition checks
- `_permissions.py` — Bot permission map + check_bot_permissions() + RISK_LEVELS
- `_helpers.py` — Shared utilities (image download, build_overwrites, RateLimitGate, coerce_*)

### Two-Layer Permission Model

**Layer 1 (Bot Permission):** Each connector method checks bot permissions
via `check_bot_permissions(guild, tool_name)` before calling Discord API.

**Layer 2 (Application Auth):** `auth_service.py` verifies the Discord
message author is Owner/Admin BEFORE the request reaches connectors.
Connectors trust that the caller has been authenticated.

### **kwargs Pattern with Guard Rails

Every action method that accepts dynamic params uses `**kwargs`:
```python
async def create(self, guild: Guild, name: str, type: str, **kwargs) -> Dict:
    # 1. Validate kwargs against whitelist
    clean = validate_kwargs("discord.channels.create", kwargs, context=type)
    # 2. Extract permission-related keys
    overwrites = build_overwrites(guild, **extract_permission_kwargs(clean))
    # 3. Spread remaining clean kwargs into Nextcord API
    channel = await guild.create_text_channel(name=name, **clean)
```

### Return Format (all actions)
```python
{
    "id": str,           # Primary resource ID
    "name": str,         # Resource name
    ...                  # Action-specific fields
}
```
Errors are raised as exceptions (ValueError, PermissionError, RuntimeError)
and caught by the MCP server layer which formats them into MCPResponse.

### Risk Level Enforcement
Each tool has a risk level in `_permissions.RISK_LEVELS`. The executor/approval
layer reads this to decide auto-execute vs confirm vs double-confirm.

---

## Connector Files

| File | Tools | Schema Section |
|------|-------|---------------|
| channels.py | create, edit, delete, move, rename, list | Create Channel flow |
| categories.py | create, edit, delete, sync, list | Create Category flow |
| roles.py | create, modify, delete, assign, batch_assign, clone, set_position, get_info, list | — |
| members.py | kick, ban, unban, bulk_ban, timeout, purge, get_info | — |
| guild.py | get_info, edit_profile, set_verification, set_community, set_system_channels, set_default_notifications, set_afk, set_preferred_locale | §2-3-8 |
| safety.py | set_content_filter, set_raid_protection, set_mfa, automod_preset | §5 |
| audit.py | query | §6 |
| events.py | create, edit, cancel, list | §10 Events flow |
| webhooks.py | create, delete, list | §4 |
| stickers.py | upload, edit, delete, list | §9 |
| soundboard.py | upload, edit, delete, list | §9 |
| templates.py | create, sync, delete, list | §7 |
| integrations.py | list, remove | §4 |
| backup.py | export, restore | — |
| features.py | setup_verification, create_poll, setup_welcome, configure_auto_delete | Bot-specific |
| connector.py | Unified dispatch + tool definition registry | — |

---

## Tool Descriptions for LLM (exposed in Planner prompt)

Each connector registers its tools with structured descriptions including:
- `name`: Dotted tool name
- `description`: What the tool does
- `required_params`: Must be provided
- `optional_params`: Context-dependent, from PARAM_WHITELIST
- `risk_level`: From RISK_LEVELS
- `preconditions`: Human-readable prerequisites

This registry is used by `planner_service.py` to generate the tool list
section of the system prompt — LLM knows exactly what params are available.

---

## Files to DELETE (unused/superseded)

- `app/connectors/discord/exceptions.py` → errors are standard Python exceptions
- `app/connectors/discord/invites.py` → not in schema, minimal value
- `app/connectors/discord/onboarding.py` → merged into guild.py set_community
- `app/connectors/discord/threads.py` → not in schema scope
- `app/connectors/discord/emojis.py` → superseded by stickers.py

Root-level files to delete:
- `AuraFactory/discord_category.py` → was a duplicate/draft
- `AuraFactory/discord-tool-schema-part2.md` → moved to spec location

---

## Notes

- All code and comments in English
- Bot responses auto-detect user language (vi/en)
- MCP protocol wraps all tool calls — connectors are pure business logic
- Rate limit: executor sleeps 0.3s between steps; backup uses RateLimitGate(5, 1.5)
