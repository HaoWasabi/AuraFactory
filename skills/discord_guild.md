# discord.guild — Knowledge for LLM

## Available Actions
- get_info, edit_profile, set_community, set_preferred_locale, set_verification, set_system_channels, set_afk, set_notifications, set_widget

## Key Rules

### edit_profile (batch edit multiple fields at once)
Params: name, description, icon_url, banner_url, verification_level, explicit_content_filter, preferred_locale
- icon_url: pass "" (empty string) to REMOVE current icon
- banner_url: requires Boost Level 2+ (premium_tier >= 2)
- Only provided params are changed, others stay unchanged

### set_community
- **CRITICAL**: Required for stage, news/announcement, and forum channels
- When enabling: needs rules_channel_id and updates_channel_id (auto-picks if not provided)
- Discord forces minimum verification_level = "low" when Community is on
- Disabling Community removes: Discovery, Welcome Screen, Onboarding features

### set_verification
Levels (ascending strictness):
| Level | Requirement |
|-------|-------------|
| none | No restriction |
| low | Must have verified email |
| medium | Registered on Discord > 5 min |
| high | Member of server > 10 min |
| highest | Must have verified phone |

### set_system_channels
- system_channel_id: where join/boost messages appear
- suppress_join_notifications: true = hide "X joined" messages
- suppress_premium_subscriptions: true = hide boost messages

### set_afk
- afk_channel_id: must be a VOICE channel
- afk_timeout: only valid values are 60, 300, 900, 1800, 3600 (seconds)

### set_preferred_locale
Common values: en-US, vi, ja, ko, zh-CN, zh-TW, fr, de, es-ES, pt-BR, ru, tr

### Common Patterns
1. **New server setup**: set_community(enable=true) → edit_profile(name, description) → set_verification("medium")
2. **Localize server**: set_preferred_locale("vi") + edit_profile(description="...")
3. **Secure server**: set_verification("high") + edit_profile(explicit_content_filter="all_members")
