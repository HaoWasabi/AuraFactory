"""Skill Loader — Loads relevant skill knowledge docs for LLM context enrichment.

Skills are markdown files in the /skills directory that provide business logic,
parameter interaction rules, and best practices that JSON schemas cannot express.

Integration strategy:
  - On each LLM planning call, load ONLY skills relevant to the user's intent
  - Relevance is determined by matching tool modules the agent might use
  - This keeps token cost low (~200-400 tokens per relevant skill)
  - Skills are appended to the system prompt context, not the tool definitions
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Skills directory relative to project root
_SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"

# Mapping: module name → skill filename (without .md)
_MODULE_TO_SKILL: Dict[str, str] = {
    "channels": "discord_channels",
    "categories": "discord_categories",
    "roles": "discord_roles",
    "permissions": "discord_permissions",
    "members": "discord_moderation",
    "guild": "discord_guild",
    "onboarding": "discord_onboarding",
    "backup": "discord_backup",
    "webhooks": "discord_webhooks",
}


class SkillLoader:
    """Loads and caches skill markdown content for injection into LLM prompts."""

    def __init__(self, skills_dir: Optional[Path] = None) -> None:
        self._dir = skills_dir or _SKILLS_DIR
        self._cache: Dict[str, str] = {}
        self._load_all()

    def _load_all(self) -> None:
        """Pre-load all skill files into memory cache."""
        if not self._dir.exists():
            logger.warning("Skills directory not found: %s", self._dir)
            return

        for md_file in self._dir.glob("*.md"):
            name = md_file.stem  # e.g. "discord_channels"
            try:
                content = md_file.read_text(encoding="utf-8")
                self._cache[name] = content
                logger.debug("Loaded skill: %s (%d chars)", name, len(content))
            except Exception as e:
                logger.warning("Failed to load skill %s: %s", name, e)

        logger.info("SkillLoader: %d skills loaded from %s", len(self._cache), self._dir)

    def get_relevant_skills(self, tool_names: Optional[List[str]] = None, modules: Optional[Set[str]] = None) -> str:
        """Get concatenated skill docs relevant to the given tools/modules.

        Args:
            tool_names: List of MCP tool names (e.g. ["discord.channels.create", "discord.roles.assign"])
            modules: Set of module names directly (e.g. {"channels", "roles"})

        Returns:
            Concatenated skill content for injection into prompt. Empty string if no matches.
        """
        relevant_modules: Set[str] = modules or set()

        # Extract modules from tool names
        if tool_names:
            for name in tool_names:
                parts = name.split(".")
                if len(parts) >= 2:
                    relevant_modules.add(parts[1])

        if not relevant_modules:
            # No specific modules → return general skills (guild + channels + roles)
            relevant_modules = {"guild", "channels", "roles"}

        # Collect matching skill content
        sections: List[str] = []
        seen_skills: Set[str] = set()

        for module in relevant_modules:
            skill_name = _MODULE_TO_SKILL.get(module)
            if skill_name and skill_name in self._cache and skill_name not in seen_skills:
                sections.append(self._cache[skill_name])
                seen_skills.add(skill_name)

        if not sections:
            return ""

        return "\n\n---\n\n".join(sections)

    def get_all_skills_summary(self) -> str:
        """Get a one-line summary of each skill (for general context).

        Used when no specific modules are identified yet (first LLM call).
        """
        lines = []
        for skill_name, content in self._cache.items():
            # Extract first line (# title)
            first_line = content.split("\n")[0].replace("#", "").strip()
            lines.append(f"- {first_line}")
        return "\n".join(lines)

    @property
    def skill_count(self) -> int:
        return len(self._cache)
