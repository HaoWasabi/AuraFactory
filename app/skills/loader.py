"""SkillLoader — parses markdown skill definition files into SkillTool objects.

Skill files follow a specific markdown format with tool definitions
including name, description, risk level, agent assignment, and parameters.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SkillParameter:
    """A single parameter for a skill tool."""

    name: str
    type: str
    required: bool
    description: str


@dataclass
class SkillTool:
    """A parsed skill tool definition.

    Attributes:
        name: Full MCP tool name (e.g., discord.channels.create).
        description: What the tool does.
        risk: Risk level (low, medium, high, critical).
        agent: Agent role assignment (admin, assistant, fast_track).
        parameters: List of parameter definitions.
        skill_file: Source .md file path.
    """

    name: str
    description: str
    risk: str
    agent: str
    parameters: list[SkillParameter] = field(default_factory=list)
    skill_file: str = ""


# Regex patterns for parsing
SKILL_NAME_PATTERN: re.Pattern[str] = re.compile(r"^#\s+(.+)$", re.MULTILINE)
TOOL_HEADER_PATTERN: re.Pattern[str] = re.compile(r"^###\s+(.+)$", re.MULTILINE)
PROPERTY_PATTERN: re.Pattern[str] = re.compile(r"^-\s+(description|risk|agent):\s+(.+)$", re.MULTILINE)
PARAM_PATTERN: re.Pattern[str] = re.compile(
    r"^\s+-\s+(\w+)\s+\((\w+),\s*(required|optional)\):\s+(.+)$", re.MULTILINE
)


class SkillLoader:
    """Loads and parses markdown skill definition files.

    Parses the structured markdown format into SkillTool dataclass
    objects for registration in the SkillRegistry.
    """

    def load_skill_file(self, path: str) -> list[SkillTool]:
        """Parse a markdown skill file and extract tool definitions.

        Args:
            path: Path to the .md skill file.

        Returns:
            List of SkillTool objects parsed from the file.

        Raises:
            FileNotFoundError: If the skill file does not exist.
            ValueError: If the file format is invalid.
        """
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Skill file not found: {path}")

        content = file_path.read_text(encoding="utf-8")
        return self._parse_content(content, str(file_path))

    def _parse_content(self, content: str, source_file: str) -> list[SkillTool]:
        """Parse markdown content into SkillTool objects.

        Args:
            content: Raw markdown text.
            source_file: Source file path for reference.

        Returns:
            List of parsed SkillTool objects.
        """
        # Extract skill name (module name from H1)
        skill_match = SKILL_NAME_PATTERN.search(content)
        if not skill_match:
            raise ValueError(f"No skill name (H1 header) found in {source_file}")

        skill_name = skill_match.group(1).strip()
        tools: list[SkillTool] = []

        # Split content by tool headers (### tool_name)
        tool_sections = self._split_tool_sections(content)

        for tool_name, section_content in tool_sections:
            tool = self._parse_tool_section(skill_name, tool_name, section_content, source_file)
            if tool is not None:
                tools.append(tool)

        logger.info("Loaded %d tools from %s (skill: %s)", len(tools), source_file, skill_name)
        return tools

    def _split_tool_sections(self, content: str) -> list[tuple[str, str]]:
        """Split content into (tool_name, section_content) pairs.

        Args:
            content: Full markdown content.

        Returns:
            List of (tool_name, section_text) tuples.
        """
        sections: list[tuple[str, str]] = []
        matches = list(TOOL_HEADER_PATTERN.finditer(content))

        for i, match in enumerate(matches):
            tool_name = match.group(1).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            section_text = content[start:end]
            sections.append((tool_name, section_text))

        return sections

    def _parse_tool_section(
        self, skill_name: str, tool_name: str, section: str, source_file: str
    ) -> SkillTool | None:
        """Parse a single tool section into a SkillTool.

        Args:
            skill_name: Parent skill module name.
            tool_name: Tool action name.
            section: Section markdown text.
            source_file: Source file for reference.

        Returns:
            Parsed SkillTool or None if parsing fails.
        """
        # Extract properties
        properties: dict[str, str] = {}
        for prop_match in PROPERTY_PATTERN.finditer(section):
            key = prop_match.group(1).strip()
            value = prop_match.group(2).strip()
            properties[key] = value

        description = properties.get("description", "")
        risk = properties.get("risk", "medium")
        agent = properties.get("agent", "assistant")

        if not description:
            logger.warning("Tool '%s' in %s has no description, skipping", tool_name, source_file)
            return None

        # Validate risk level
        valid_risks = {"low", "medium", "high", "critical"}
        if risk not in valid_risks:
            logger.warning("Tool '%s' has invalid risk '%s', defaulting to medium", tool_name, risk)
            risk = "medium"

        # Validate agent
        valid_agents = {"admin", "assistant", "fast_track"}
        if agent not in valid_agents:
            logger.warning("Tool '%s' has invalid agent '%s', defaulting to assistant", tool_name, agent)
            agent = "assistant"

        # Extract parameters
        parameters: list[SkillParameter] = []
        for param_match in PARAM_PATTERN.finditer(section):
            param_name = param_match.group(1).strip()
            param_type = param_match.group(2).strip()
            param_required = param_match.group(3).strip() == "required"
            param_desc = param_match.group(4).strip()
            parameters.append(
                SkillParameter(
                    name=param_name,
                    type=param_type,
                    required=param_required,
                    description=param_desc,
                )
            )

        # Build full MCP tool name: discord.{module}.{action}
        full_name = f"discord.{skill_name}.{tool_name}"

        return SkillTool(
            name=full_name,
            description=description,
            risk=risk,
            agent=agent,
            parameters=parameters,
            skill_file=source_file,
        )
