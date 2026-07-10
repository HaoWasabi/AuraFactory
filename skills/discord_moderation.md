# discord.members (moderation) — Knowledge for LLM

## Available Actions
- kick, ban, unban, bulk_ban, timeout, mute, purge, list, get_info

## Key Rules

### Action Severity (ascending)
1. `timeout` — temporary mute (1min to 28 days), member stays in server
2. `mute` — server mute in voice channel
3. `kick` — remove from server, can rejoin with invite
4. `ban` — remove + prevent rejoin, can optionally delete message history
5. `bulk_ban` — ban multiple members at once

### Parameters
- `kick`: member_id, reason
- `ban`: member_id, reason, delete_message_days (0-7, how many days of messages to purge)
- `unban`: user_id (note: user_id not member_id since they're no longer a member)
- `bulk_ban`: member_ids (list), reason, delete_message_days
- `timeout`: member_id, duration (seconds, max 2419200 = 28 days), reason
- `mute`: member_id, mute (bool), reason
- `purge`: channel_id, limit (number of messages, max 100), reason

### Hierarchy Rules
- Cannot kick/ban/timeout members with a role >= bot's highest role
- Cannot kick/ban the server owner
- Cannot timeout members with ADMINISTRATOR permission

### Duration Helpers for timeout
- 5 minutes = 300
- 1 hour = 3600
- 1 day = 86400
- 7 days = 604800
- 28 days = 2419200 (maximum)
- To remove timeout: duration = 0 or null

### Error Prevention
- Always confirm member exists before moderation (use get_info first if unsure)
- bulk_ban: max ~200 members per call recommended
- purge: only works on messages < 14 days old (Discord limitation)
