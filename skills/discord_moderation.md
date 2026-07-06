# Skill: Discord Moderation

## Agent: architect
## Risk: high
## Category: moderation

### Tools

#### kick_member
- Description: Kick a member from the server. They can rejoin with an invite.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - user_id (integer, required): Member to kick
  - reason (string, default: AI Agent Request): Audit log reason
- Risk: high
- Requires Approval: yes

#### ban_member
- Description: Ban a member — they cannot rejoin until unbanned. Optionally deletes recent messages.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - user_id (integer, required): Member to ban
  - reason (string, default: AI Agent Request): Audit log reason
  - delete_days (integer, default: 0): Days of messages to delete (0-7)
- Risk: high
- Requires Approval: yes

#### unban_member
- Description: Remove a ban, allowing the user to rejoin.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - user_id (integer, required): User to unban
  - reason (string): Audit log reason
- Risk: medium
- Requires Approval: no

#### timeout_member
- Description: Timeout (mute) a member for a duration. They cannot send messages or join voice.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - user_id (integer, required): Member to timeout
  - duration_minutes (integer, required): Timeout duration in minutes (1-40320)
  - reason (string): Audit log reason
- Risk: medium
- Requires Approval: no

#### create_automod_rule
- Description: Create an AutoMod rule to automatically moderate content.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - name (string, required): Rule name
  - trigger_type (string, required, enum: keyword|spam|mention_spam|preset): Type of trigger
  - keywords (array): Words/phrases to filter (for keyword trigger)
  - regex_patterns (array): Regex patterns to match
  - action (string, enum: block|alert|timeout, default: block): Action when triggered
  - alert_channel (string): Channel to send alerts to
- Risk: medium
- Requires Approval: no

#### delete_automod_rule
- Description: Delete an AutoMod rule.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - rule_name (string, required): Rule name to delete
- Risk: medium
- Requires Approval: no

#### list_automod_rules
- Description: List all active AutoMod rules.
- Parameters:
  - guild_id (integer, required): Target guild ID
- Risk: low
- Requires Approval: no
