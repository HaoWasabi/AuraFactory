# app/config/guild_config.py
"""
Per-Guild Configuration — Multi-Guild Support (v2.2)

Allows different settings per guild:
- Which modes are enabled (admin/assistant)
- Approval requirements
- Feature flags
- Custom prefixes

Phase 1: In-memory defaults
Phase 2: DB-backed per-guild config
"""
from typing import Dict, Any, Optional, Set
from dataclasses import dataclass, field
from app.config.settings import settings


@dataclass
class GuildSettings:
    """Configuration for a specific guild."""
    guild_id: int
    guild_name: str = ""
    
    # Modes
    workspace_mode: bool = True   # Architect tools (channel/role management)
    assistant_mode: bool = True   # Assistant agent (Q&A/onboarding)
    
    # Safety
    require_approval_for_high_risk: bool = True
    require_approval_for_critical: bool = True
    max_bulk_operations: int = 10  # Max items in bulk_create_channels etc.
    
    # Features
    memory_enabled: bool = True
    automod_enabled: bool = True
    template_enabled: bool = True
    
    # Restrictions
    allowed_channels: Set[int] = field(default_factory=set)  # Empty = all channels
    admin_role_ids: Set[int] = field(default_factory=set)    # Roles that can use high-risk ops
    
    # Custom Prompts (user-configurable per guild)
    custom_system_prompt: Optional[str] = None       # Override orchestrator system prompt
    custom_persona_name: str = "AuraFactory"         # Bot display persona
    custom_persona_tone: str = "professional"        # professional | friendly | casual | formal
    custom_instructions: str = ""                    # Additional instructions appended to prompt
    language: str = "vi"                             # Default response language: vi | en | auto
    
    def is_channel_allowed(self, channel_id: int) -> bool:
        """Check if bot should respond in this channel."""
        if not self.allowed_channels:
            return True  # Empty = all channels allowed
        return channel_id in self.allowed_channels
    
    def can_use_high_risk(self, member_role_ids: list) -> bool:
        """Check if member has permission for high-risk operations."""
        if not self.admin_role_ids:
            return True  # No restriction configured
        return bool(set(member_role_ids) & self.admin_role_ids)

    def get_system_prompt(self, default_prompt: str) -> str:
        """
        Get the effective system prompt for this guild.
        Priority: custom_system_prompt > default + custom_instructions
        """
        if self.custom_system_prompt:
            return self.custom_system_prompt
        
        prompt = default_prompt
        if self.custom_instructions:
            prompt += f"\n\n## Guild-Specific Instructions:\n{self.custom_instructions}"
        if self.language != "auto":
            prompt += f"\n\n## Language: Always respond in {'Vietnamese' if self.language == 'vi' else 'English'}."
        if self.custom_persona_name != "AuraFactory":
            prompt += f"\n\n## Persona: Your name is {self.custom_persona_name}. Tone: {self.custom_persona_tone}."
        return prompt


class GuildConfigManager:
    """
    Manages per-guild configurations.
    
    Phase 1: In-memory with sensible defaults.
    Phase 2: Load from DB on guild_join, cache in memory.
    """
    
    def __init__(self):
        self._configs: Dict[int, GuildSettings] = {}
    
    def get(self, guild_id: int) -> GuildSettings:
        """Get config for a guild. Creates default if not exists."""
        if guild_id not in self._configs:
            self._configs[guild_id] = GuildSettings(guild_id=guild_id)
        return self._configs[guild_id]
    
    def set(self, guild_id: int, **kwargs) -> GuildSettings:
        """Update guild config. Creates if not exists."""
        config = self.get(guild_id)
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
        return config
    
    def remove(self, guild_id: int):
        """Remove guild config (e.g. when bot leaves guild)."""
        self._configs.pop(guild_id, None)
    
    def is_guild_allowed(self, guild_id: int) -> bool:
        """Check if this guild is allowed to use the bot."""
        if settings.allow_all_guilds:
            return True
        allowed = settings.allowed_guild_ids
        if not allowed:
            return True  # No restriction
        return guild_id in allowed
    
    def list_guilds(self) -> Dict[int, GuildSettings]:
        """Get all configured guilds."""
        return dict(self._configs)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get manager statistics."""
        return {
            "total_guilds": len(self._configs),
            "allowed_mode": "all" if settings.allow_all_guilds else f"{len(settings.allowed_guild_ids)} guilds",
            "guilds": {
                gid: {
                    "name": cfg.guild_name,
                    "workspace_mode": cfg.workspace_mode,
                    "assistant_mode": cfg.assistant_mode,
                }
                for gid, cfg in self._configs.items()
            },
        }


# Singleton
guild_config = GuildConfigManager()
