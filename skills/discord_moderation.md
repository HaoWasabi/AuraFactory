# moderation

## Tools

### kick
- description: Kick a member from the guild
- risk: high
- agent: admin
- parameters:
  - guild_id (int, required): Target guild ID
  - member_id (int, required): Member user ID to kick
  - reason (str, optional): Audit log reason

### ban
- description: Ban a member from the guild permanently
- risk: critical
- agent: admin
- parameters:
  - guild_id (int, required): Target guild ID
  - member_id (int, required): Member user ID to ban
  - delete_message_days (int, optional): Number of days of messages to delete (0-7)
  - reason (str, optional): Audit log reason

### unban
- description: Unban a previously banned user from the guild
- risk: high
- agent: admin
- parameters:
  - guild_id (int, required): Target guild ID
  - user_id (int, required): User ID to unban
  - reason (str, optional): Audit log reason

### mute
- description: Server-mute a member in voice channels
- risk: medium
- agent: assistant
- parameters:
  - guild_id (int, required): Target guild ID
  - member_id (int, required): Member user ID to mute
  - reason (str, optional): Audit log reason

### timeout
- description: Timeout a member for a specified duration (communication disabled)
- risk: high
- agent: admin
- parameters:
  - guild_id (int, required): Target guild ID
  - member_id (int, required): Member user ID to timeout
  - duration_seconds (int, required): Timeout duration in seconds (max 2419200 = 28 days)
  - reason (str, optional): Audit log reason

### list_members
- description: List guild members with optional filtering
- risk: low
- agent: fast_track
- parameters:
  - guild_id (int, required): Target guild ID
  - limit (int, optional): Maximum members to return (default 100)
  - role_id (int, optional): Filter by role membership
  - query (str, optional): Search by username or nickname
