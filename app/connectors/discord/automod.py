# app/tools/discord/automod.py
"""
Discord AutoMod Management Tools.
Create, list, delete AutoMod rules.
"""
from typing import Optional, Dict, Any, List
import nextcord


async def create_automod_rule(
    guild: nextcord.Guild,
    rule_name: str,
    rule_type: str = "keyword",  # "keyword" | "spam" | "mention_spam" | "keyword_preset"
    keyword_filter: Optional[List[str]] = None,
    regex_patterns: Optional[List[str]] = None,
    allow_list: Optional[List[str]] = None,
    actions: Optional[List[str]] = None,  # "block" | "alert" | "timeout"
    alert_channel_name: Optional[str] = None,
    timeout_duration: int = 60,  # seconds
    exempt_roles: Optional[List[str]] = None,
    exempt_channels: Optional[List[str]] = None,
    reason: str = "AI Agent Request",
) -> Dict[str, Any]:
    """
    Create an AutoMod rule.
    
    Args:
        rule_name: Name of the rule
        rule_type: Type — "keyword" (custom words), "spam" (general spam),
                   "mention_spam" (mass mentions), "keyword_preset" (Discord's presets)
        keyword_filter: List of blocked words/phrases (for keyword type)
        regex_patterns: List of regex patterns to block
        allow_list: Words to allow (exceptions)
        actions: What to do — "block", "alert", "timeout"
        alert_channel_name: Channel to send alerts to
        timeout_duration: Timeout in seconds (if timeout action)
        exempt_roles: Role names exempt from this rule
        exempt_channels: Channel names exempt from this rule
    """
    try:
        # Determine trigger type
        if rule_type == "keyword":
            trigger = nextcord.AutoModerationTriggerMetadata(
                keyword_filter=keyword_filter or [],
                regex_patterns=regex_patterns or [],
                allow_list=allow_list or [],
            )
            trigger_type = nextcord.AutoModerationRuleTriggerType.keyword
        elif rule_type == "spam":
            trigger = nextcord.AutoModerationTriggerMetadata()
            trigger_type = nextcord.AutoModerationRuleTriggerType.spam
        elif rule_type == "mention_spam":
            trigger = nextcord.AutoModerationTriggerMetadata(
                mention_total_limit=5,  # default: flag at 5+ mentions
            )
            trigger_type = nextcord.AutoModerationRuleTriggerType.mention_spam
        elif rule_type == "keyword_preset":
            trigger = nextcord.AutoModerationTriggerMetadata(
                presets=[
                    nextcord.AutoModerationRuleKeywordPresetType.profanity,
                    nextcord.AutoModerationRuleKeywordPresetType.slurs,
                    nextcord.AutoModerationRuleKeywordPresetType.sexual_content,
                ],
                allow_list=allow_list or [],
            )
            trigger_type = nextcord.AutoModerationRuleTriggerType.keyword_preset
        else:
            return {"success": False, "error": f"Unknown rule_type: {rule_type}"}

        # Build actions
        rule_actions = []
        action_list = actions or ["block"]
        
        for action_name in action_list:
            if action_name == "block":
                rule_actions.append(
                    nextcord.AutoModerationRuleAction(
                        type=nextcord.AutoModerationRuleActionType.block_message
                    )
                )
            elif action_name == "alert":
                alert_channel = None
                if alert_channel_name:
                    alert_channel = nextcord.utils.get(guild.text_channels, name=alert_channel_name)
                if alert_channel:
                    rule_actions.append(
                        nextcord.AutoModerationRuleAction(
                            type=nextcord.AutoModerationRuleActionType.send_alert_message,
                            channel_id=alert_channel.id,
                        )
                    )
            elif action_name == "timeout":
                rule_actions.append(
                    nextcord.AutoModerationRuleAction(
                        type=nextcord.AutoModerationRuleActionType.timeout,
                        duration=timeout_duration,
                    )
                )

        if not rule_actions:
            rule_actions.append(
                nextcord.AutoModerationRuleAction(
                    type=nextcord.AutoModerationRuleActionType.block_message
                )
            )

        # Resolve exempt roles
        exempt_role_ids = []
        if exempt_roles:
            for role_name in exempt_roles:
                role = nextcord.utils.get(guild.roles, name=role_name)
                if role:
                    exempt_role_ids.append(role)

        # Resolve exempt channels
        exempt_channel_ids = []
        if exempt_channels:
            for ch_name in exempt_channels:
                ch = nextcord.utils.get(guild.channels, name=ch_name)
                if ch:
                    exempt_channel_ids.append(ch)

        rule = await guild.create_automod_rule(
            name=rule_name,
            trigger_type=trigger_type,
            trigger_metadata=trigger,
            actions=rule_actions,
            enabled=True,
            exempt_roles=exempt_role_ids or None,
            exempt_channels=exempt_channel_ids or None,
            reason=reason,
        )

        return {
            "success": True,
            "rule_id": rule.id,
            "rule_name": rule.name,
            "type": rule_type,
            "keywords": keyword_filter,
        }
    except nextcord.Forbidden:
        return {"success": False, "error": "Bot lacks Manage Server permission"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def list_automod_rules(guild: nextcord.Guild) -> Dict[str, Any]:
    """List all AutoMod rules in the guild."""
    try:
        rules = await guild.fetch_automod_rules()
        rules_data = []
        for rule in rules:
            rules_data.append({
                "id": rule.id,
                "name": rule.name,
                "enabled": rule.enabled,
                "trigger_type": str(rule.trigger_type),
                "actions": [str(a.type) for a in rule.actions],
            })
        
        return {"success": True, "rules": rules_data, "count": len(rules_data)}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def delete_automod_rule(
    guild: nextcord.Guild,
    rule_name: str,
    reason: str = "AI Agent Request",
) -> Dict[str, Any]:
    """Delete an AutoMod rule by name."""
    try:
        rules = await guild.fetch_automod_rules()
        target = None
        for rule in rules:
            if rule.name == rule_name:
                target = rule
                break
        
        if not target:
            return {"success": False, "error": f"AutoMod rule '{rule_name}' not found"}

        await target.delete(reason=reason)
        return {"success": True, "deleted": rule_name}
    except Exception as e:
        return {"success": False, "error": str(e)}
