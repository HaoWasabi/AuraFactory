# Planner Output Schema — SPEC v2

> Defines the JSON output format the LLM MUST produce in ALL cases.
> No prose output allowed — everything is JSON.

---

## Output Schema (single unified format)

```json
{
  "status": "ready" | "clarify",
  "summary": "string — one-line description of what will be done (or why we need info)",
  "questions": [],       // empty if status=ready; list of strings if status=clarify
  "steps": []            // populated if status=ready; empty if status=clarify
}
```

### When `status = "ready"`:
```json
{
  "status": "ready",
  "summary": "Tạo 3 kênh text và 2 role cho server học tiếng Anh",
  "questions": [],
  "steps": [
    {
      "tool_name": "discord.channels.create",
      "description": "Tạo kênh #general-english",
      "tool_params": {
        "guild_id": "123456789",
        "name": "general-english",
        "type": "text",
        "category_id": "987654321",
        "topic": "General English discussion"
      },
      "risk_level": "MEDIUM"
    }
  ]
}
```

### When `status = "clarify"`:
```json
{
  "status": "clarify",
  "summary": "Cần thêm thông tin về cấu trúc server",
  "questions": [
    "Bạn muốn tạo những role nào? (VD: Học viên, Giáo viên...)",
    "Server cần bao nhiêu kênh voice cho luyện nói?"
  ],
  "steps": []
}
```

---

## Parse Logic (in planner_service.py)

```python
def _parse_plan_response(self, content: str) -> Optional[dict]:
    # 1. Try JSON parse (strip markdown fences)
    # 2. If JSON valid:
    #    a. Check "status" field
    #    b. If status="clarify" → return as-is (questions flow)
    #    c. If status="ready" → validate steps
    # 3. If JSON invalid (LLM output prose):
    #    → Create synthetic clarify response:
    #    {"status": "clarify", "summary": "...", "questions": [raw_text], "steps": []}
```

---

## Simulation: All tool categories

Below simulates planner output for each tool group to verify param correctness
against PARAM_WHITELIST in _validation.py.

---

### SIM 1: Channel Create (text, voice, stage, forum, news)

```json
// TEXT channel in category
{
  "status": "ready",
  "summary": "Tạo kênh text #rules trong category THÔNG BÁO",
  "steps": [{
    "tool_name": "discord.channels.create",
    "description": "Tạo kênh #rules (read-only)",
    "tool_params": {
      "guild_id": "111",
      "name": "rules",
      "type": "text",
      "category_id": "222",
      "topic": "Server rules - read carefully",
      "advanced_permissions": {"send_messages": false, "view_channel": true}
    },
    "risk_level": "MEDIUM"
  }]
}

// VOICE channel with limits
{
  "tool_name": "discord.channels.create",
  "tool_params": {
    "guild_id": "111",
    "name": "Speaking Practice",
    "type": "voice",
    "category_id": "333",
    "user_limit": 5,
    "bitrate": 96000
  },
  "risk_level": "MEDIUM"
}

// STAGE channel (requires Community)
{
  "tool_name": "discord.channels.create",
  "tool_params": {
    "guild_id": "111",
    "name": "Weekly Podcast",
    "type": "stage",
    "category_id": "444",
    "topic": "English podcast every Saturday"
  },
  "risk_level": "MEDIUM"
}
// PRECONDITION: check_community_required(guild) 
// If fails → error before API call

// FORUM channel
{
  "tool_name": "discord.channels.create",
  "tool_params": {
    "guild_id": "111",
    "name": "homework-help",
    "type": "forum",
    "topic": "Post your homework questions here",
    "slowmode_delay": 60
  },
  "risk_level": "MEDIUM"
}

// PRIVATE channel
{
  "tool_name": "discord.channels.create",
  "tool_params": {
    "guild_id": "111",
    "name": "staff-chat",
    "type": "text",
    "is_private": true,
    "allowed_role_ids": ["555", "666"]
  },
  "risk_level": "MEDIUM"
}
```

**Validation check (channels.create):**
- `_common`: category_id ✅, position ✅, is_private ✅, allowed_role_ids ✅, allowed_user_ids ✅, advanced_permissions ✅, reason ✅
- `text`: topic ✅, slowmode_delay ✅, nsfw ✅
- `voice`: bitrate ✅, user_limit ✅, rtc_region ✅
- `stage`: topic ✅
- `forum`: topic ✅, slowmode_delay ✅, default_auto_archive_duration ✅
- ❌ LLM might pass `topic` to voice → whitelist drops it → OK (silent drop)
- ❌ LLM might pass `bitrate` to text → whitelist drops it → OK

---

### SIM 2: Channel Edit

```json
{
  "tool_name": "discord.channels.edit",
  "tool_params": {
    "guild_id": "111",
    "channel_id": "888",
    "name": "announcements",
    "topic": "Important server news",
    "slowmode_delay": 0
  },
  "risk_level": "MEDIUM"
}

// Permission update for a role
{
  "tool_name": "discord.channels.edit",
  "tool_params": {
    "guild_id": "111",
    "channel_id": "888",
    "update_permissions": {
      "target_id": "999",
      "permissions": {"send_messages": false}
    }
  },
  "risk_level": "MEDIUM"
}
```

**Note:** `channel_id` is a required param (not in whitelist — it's a positional arg in the method).

---

### SIM 3: Channel Delete

```json
{
  "tool_name": "discord.channels.delete",
  "tool_params": {
    "guild_id": "111",
    "channel_id": "777",
    "reason": "No longer needed"
  },
  "risk_level": "HIGH"
}
```

---

### SIM 4: Category CRUD

```json
// Create private category
{
  "tool_name": "discord.categories.create",
  "tool_params": {
    "guild_id": "111",
    "name": "STAFF AREA",
    "is_private": true,
    "allowed_role_ids": ["555"]
  },
  "risk_level": "MEDIUM"
}

// Sync permissions
{
  "tool_name": "discord.categories.sync",
  "tool_params": {
    "guild_id": "111",
    "category_id": "222"
  },
  "risk_level": "MEDIUM"
}
```

---

### SIM 5: Role CRUD

```json
// Create role with permissions
{
  "tool_name": "discord.roles.create",
  "tool_params": {
    "guild_id": "111",
    "role_name": "Teacher",
    "color": "#e74c3c",
    "hoist": true,
    "mentionable": true,
    "permissions": {"manage_messages": true, "mute_members": true}
  },
  "risk_level": "MEDIUM"
}

// Modify role (merge permissions — non-destructive)
{
  "tool_name": "discord.roles.modify",
  "tool_params": {
    "guild_id": "111",
    "role_id": "444",
    "name": "Senior Teacher",
    "color": "#9b59b6",
    "permissions": {"kick_members": true}
  },
  "risk_level": "MEDIUM"
}

// Batch assign
{
  "tool_name": "discord.roles.batch_assign",
  "tool_params": {
    "guild_id": "111",
    "role_id": "444",
    "member_ids": ["101", "102", "103"],
    "action": "add"
  },
  "risk_level": "MEDIUM"
}
```

**Note:** `role_name` → maps to `name` param in roles.create. LLM uses `role_name` as the method's positional arg.

---

### SIM 6: Members / Moderation

```json
// Ban
{
  "tool_name": "discord.members.ban",
  "tool_params": {
    "guild_id": "111",
    "member_id": "999",
    "delete_message_seconds": 86400,
    "reason": "Spam"
  },
  "risk_level": "CRITICAL"
}

// Bulk ban (max 200)
{
  "tool_name": "discord.members.bulk_ban",
  "tool_params": {
    "guild_id": "111",
    "member_ids": ["901", "902", "903"],
    "delete_message_seconds": 0,
    "reason": "Raid accounts"
  },
  "risk_level": "CRITICAL"
}

// Timeout
{
  "tool_name": "discord.members.timeout",
  "tool_params": {
    "guild_id": "111",
    "member_id": "888",
    "duration_minutes": 30,
    "reason": "Repeated warnings"
  },
  "risk_level": "HIGH"
}

// Purge
{
  "tool_name": "discord.members.purge",
  "tool_params": {
    "guild_id": "111",
    "channel_id": "777",
    "limit": 50,
    "member_id": "888"
  },
  "risk_level": "CRITICAL"
}
```

---

### SIM 7: Guild Settings

```json
// Edit profile
{
  "tool_name": "discord.guild.edit_profile",
  "tool_params": {
    "guild_id": "111",
    "new_name": "English Learning Hub",
    "description": "Community for English learners"
  },
  "risk_level": "MEDIUM"
}

// Set verification
{
  "tool_name": "discord.guild.set_verification",
  "tool_params": {
    "guild_id": "111",
    "level": "medium"
  },
  "risk_level": "HIGH"
}
```

---

### SIM 8: Safety

```json
// Content filter
{
  "tool_name": "discord.safety.set_content_filter",
  "tool_params": {
    "guild_id": "111",
    "level": "all_members"
  },
  "risk_level": "HIGH"
}

// AutoMod preset
{
  "tool_name": "discord.safety.automod_preset",
  "tool_params": {
    "guild_id": "111",
    "preset_type": "profanity",
    "enabled": true,
    "exempt_role_ids": ["555"]
  },
  "risk_level": "HIGH"
}
```

---

### SIM 9: Engagement

```json
// System channels
{
  "tool_name": "discord.engagement.set_system_channels",
  "tool_params": {
    "guild_id": "111",
    "system_channel_id": "222",
    "suppress_join_notifications": false,
    "suppress_premium_subscriptions": true
  },
  "risk_level": "LOW"
}

// AFK
{
  "tool_name": "discord.engagement.set_afk",
  "tool_params": {
    "guild_id": "111",
    "afk_channel_id": "333",
    "afk_timeout": 300
  },
  "risk_level": "LOW"
}
// PRECONDITION: check_afk_timeout(300) → OK (in valid set)
// PRECONDITION: check_afk_channel_is_voice(guild, 333) → must be VoiceChannel
```

---

### SIM 10: Community Toggle

```json
// Enable
{
  "tool_name": "discord.community.toggle",
  "tool_params": {
    "guild_id": "111",
    "enable": true,
    "rules_channel_id": "222",
    "public_updates_channel_id": "333"
  },
  "risk_level": "HIGH"
}
// PRECONDITION: check_community_prerequisites(guild) 
// → verification_level >= medium, content_filter = all_members
```

---

### SIM 11: Events

```json
{
  "tool_name": "discord.events.create",
  "tool_params": {
    "guild_id": "111",
    "name": "English Speaking Night",
    "start_time": "2025-08-01T19:00:00+07:00",
    "end_time": "2025-08-01T21:00:00+07:00",
    "entity_type": "voice",
    "channel_id": "444",
    "description": "Practice speaking with native speakers"
  },
  "risk_level": "MEDIUM"
}
```

---

### SIM 12: Audit Log (read-only)

```json
{
  "tool_name": "discord.audit.query",
  "tool_params": {
    "guild_id": "111",
    "limit": 20
  },
  "risk_level": "LOW"
}
```

---

### SIM 13: Webhooks

```json
{
  "tool_name": "discord.webhooks.create",
  "tool_params": {
    "guild_id": "111",
    "channel_id": "222",
    "webhook_name": "GitHub Notifications"
  },
  "risk_level": "MEDIUM"
}
```

---

### SIM 14: Backup

```json
{
  "tool_name": "discord.backup.export",
  "tool_params": {
    "guild_id": "111"
  },
  "risk_level": "LOW"
}
```

---

## Edge Cases Handled by Fallback

| LLM Output | What happens |
|---|---|
| Valid JSON with `status=ready` + steps | Normal plan execution |
| Valid JSON with `status=clarify` + questions | Send questions back to user |
| Prose text (no JSON at all) | Fallback: wrap in `{status: "clarify", questions: [text]}` |
| JSON with missing `status` field | Default to `status="ready"` if steps exist |
| JSON with `steps: []` and no `questions` | Treat as error: "Could not generate plan" |
| Truncated JSON | Existing repair logic (close brackets) → then apply above rules |

---

## Param Routing: How `tool_params` map to connector methods

Tool params from LLM plan include `guild_id` (always) + method-specific params.

**Executor flow:**
```
guild_id → resolved to guild object (by MCP server)
Remaining params → passed as **kwargs to connector method

Example: discord.channels.create
  tool_params: {guild_id, name, type, category_id, topic, ...}
  → connector.execute("discord.channels.create", guild=guild, name=name, type=type, **rest)
  → ChannelsConnector.create(guild, name, type, **rest)
  → validate_kwargs("discord.channels.create", rest, context=type)
  → Nextcord API call
```

**Key insight:** `guild_id` is popped by MCP server. Required positional args (`name`, `type`, `channel_id`, `member_id`, `role_id`) are extracted by the connector method signature. Only optional params flow through **kwargs → validation.

---

## Changes Required in planner_service.py

1. **Update `PLANNER_SYSTEM_PROMPT`** — add output format instruction with `status` field
2. **Update `_parse_plan_response()`** — handle `status=clarify` + fallback for prose
3. **Update caller** — when `status=clarify`, send questions to user instead of failing
4. **Keep existing step validation** — `_validate_and_fix_steps()` unchanged (still needed)
5. **Keep existing risk calculation** — applied after parse, only when `status=ready`
