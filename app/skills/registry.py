"""SkillRegistry — central registry for all skill tools.

Provides lookup by name, agent role, risk level, and formatting
for LLM system prompt injection.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.skills.loader import SkillLoader, SkillTool

logger = logging.getLogger(__name__)

RISK_LEVELS: list[str] = ["low", "medium", "high", "critical"]


class SkillRegistry:
    """Central registry for all loaded skill tools.

    Supports lookup by name, filtering by agent role and risk level,
    and formatting tool lists for LLM prompt injection.
    """

    def __init__(self) -> None:
        self._tools: dict[str, SkillTool] = {}
        self._loader = SkillLoader()
        logger.info("SkillRegistry initialized")

    # ============================================================
    # INITIALIZATION — load all skill files from skills/ directory
    # ============================================================

    async def init_skills(self) -> None:
        """Load all skill definition files from the skills/ directory.

        Scans for .md files in the skills directory and registers
        all tools found in them.
        """
        from app.config.settings import settings

        skills_dir = Path(settings.skills_dir)
        if not skills_dir.exists():
            logger.warning("Skills directory not found: %s", skills_dir)
            return

        skill_files = list(skills_dir.glob("*.md"))
        if not skill_files:
            logger.info("No skill files found in %s", skills_dir)
            return

        for skill_file in skill_files:
            try:
                tools = self._loader.load_skill_file(str(skill_file))
                for tool in tools:
                    self.register_skill(tool)
            except Exception as e:
                logger.warning("Failed to load skill file %s: %s", skill_file.name, e)

        logger.info("Loaded %d skills from %d files", len(self._tools), len(skill_files))

    # ============================================================
    # REGISTRATION & LOOKUP
    # ============================================================

    def register_skill(self, skill_tool: SkillTool) -> None:
        """Register a skill tool in the registry.

        Args:
            skill_tool: SkillTool instance to register.

        Raises:
            ValueError: If tool name already registered.
        """
        if skill_tool.name in self._tools:
            logger.warning("Overwriting existing tool: %s", skill_tool.name)

        self._tools[skill_tool.name] = skill_tool
        logger.debug("Registered tool: %s (risk=%s, agent=%s)", skill_tool.name, skill_tool.risk, skill_tool.agent)

    def get_tools_for_agent(self, agent_role: str) -> list[SkillTool]:
        """Get all tools assigned to a specific agent role.

        Args:
            agent_role: Agent role name (admin, assistant, fast_track).

        Returns:
            List of SkillTool objects assigned to the role.
        """
        tools = [tool for tool in self._tools.values() if tool.agent == agent_role]
        logger.debug("Found %d tools for agent role '%s'", len(tools), agent_role)
        return tools

    def get_tools_by_risk(self, max_risk: str) -> list[SkillTool]:
        """Get all tools at or below the specified risk level.

        Risk hierarchy: low < medium < high < critical

        Args:
            max_risk: Maximum risk level to include.

        Returns:
            List of SkillTool objects at or below max_risk.
        """
        if max_risk not in RISK_LEVELS:
            logger.warning("Invalid risk level '%s', using 'medium'", max_risk)
            max_risk = "medium"

        max_index = RISK_LEVELS.index(max_risk)
        tools = [
            tool
            for tool in self._tools.values()
            if RISK_LEVELS.index(tool.risk) <= max_index
        ]
        logger.debug("Found %d tools at or below risk '%s'", len(tools), max_risk)
        return tools

    def get_tool(self, name: str) -> SkillTool | None:
        """Get a specific tool by its full name.

        Args:
            name: Full MCP tool name (e.g., discord.channels.create).

        Returns:
            SkillTool instance or None if not found.
        """
        return self._tools.get(name)

    def get_all_tools(self) -> list[SkillTool]:
        """Get all registered tools.

        Returns:
            List of all SkillTool objects.
        """
        return list(self._tools.values())

    def format_tools_for_prompt(self, tools: list[SkillTool]) -> str:
        """Format a list of tools for LLM system prompt injection.

        Produces a structured text block describing available tools
        with their parameters for the LLM to understand and invoke.

        Args:
            tools: List of SkillTool objects to format.

        Returns:
            Formatted string for system prompt injection.
        """
        if not tools:
            return "No tools available."

        lines: list[str] = ["## Available Tools\n"]

        for tool in tools:
            lines.append(f"### {tool.name}")
            lines.append(f"  Description: {tool.description}")
            lines.append(f"  Risk: {tool.risk}")

            if tool.parameters:
                lines.append("  Parameters:")
                for param in tool.parameters:
                    req_str = "REQUIRED" if param.required else "optional"
                    lines.append(f"    - {param.name} ({param.type}, {req_str}): {param.description}")

            lines.append("")

        formatted = "\n".join(lines)
        logger.debug("Formatted %d tools for prompt (%d chars)", len(tools), len(formatted))
        return formatted

    # ============================================================
    # CONVENIENCE METHODS (used by main.py)
    # ============================================================

    def count(self) -> int:
        """Return the number of registered tools."""
        return len(self._tools)

    @property
    def tool_count(self) -> int:
        """Total number of registered tools."""
        return len(self._tools)

    @property
    def tool_names(self) -> list[str]:
        """List of all registered tool names."""
        return list(self._tools.keys())
