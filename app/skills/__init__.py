"""AuraFactory Skills System — Layer 6.

Provides skill loading, registration, validation, and prompt injection
for the multi-agent tool system.
"""

from app.skills.registry import SkillRegistry

__all__: list[str] = ["SkillRegistry"]
