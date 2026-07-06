# Skill: Discord Onboarding & Welcome

## Agent: architect
## Risk: medium
## Category: onboarding

### Tools

#### setup_welcome
- Description: Configure welcome message and rules screen for new members.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - welcome_channel (string, required): Channel name for welcome messages
  - welcome_message (string, required): Message template ({user} = mention, {server} = server name)
  - rules_channel (string): Channel for rules (enables Rules Screen)
  - enable_rules_screen (boolean, default: true): Show rules before joining
- Risk: medium
- Requires Approval: no

#### setup_onboarding_flow
- Description: Configure Discord's native onboarding flow (prompts, default channels).
- Parameters:
  - guild_id (integer, required): Target guild ID
  - default_channels (array, required): Channels new members see by default
  - prompts (array): Onboarding prompts (questions for new members)
  - mode (string, enum: default|advanced, default: default): Onboarding mode
- Risk: medium
- Requires Approval: no

#### set_system_channel
- Description: Configure system channel for join/boost/etc notifications.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - channel_name (string, required): Channel for system messages
  - join_notifications (boolean, default: true): Show member join messages
  - boost_notifications (boolean, default: true): Show boost messages
- Risk: medium
- Requires Approval: no

#### create_invite
- Description: Create an invite link with custom settings.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - channel_name (string, required): Channel the invite points to
  - max_age (integer, default: 86400): Expiry in seconds (0 = never)
  - max_uses (integer, default: 0): Max uses (0 = unlimited)
  - temporary (boolean, default: false): Grant temporary membership
- Risk: medium
- Requires Approval: no

#### revoke_invite
- Description: Revoke/delete an invite link.
- Parameters:
  - guild_id (integer, required): Target guild ID
  - invite_code (string, required): Invite code to revoke
- Risk: medium
- Requires Approval: no
