# app/skills/loader.py
"""
Skill Loader — parses SKILL.md definition files into SkillTool objects.
Each .md file defines a group of related tools (e.g., discord_channels.md).
Format follows a structured markdown convention.
"""
import re
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

from app.skills.registry import SkillTool

logger = logging.getLogger(__name__)


class SkillLoader:
    """
    Parse SKILL.md files into SkillTool objects.
    Supports the markdown format defined in docs/specs/04_skills_registry.md.
    """

    @staticmethod
    def load_directory(path: str = "./skills") -> List[SkillTool]:
        """Load all .md skill files from a directory."""
        skills_path = Path(path)
        if not skills_path.exists():
            logger.warning(f"Skills directory not found: {path}")
            return []

        tools = []
        for md_file in sorted(skills_path.glob("*.md")):
            try:
                file_tools = SkillLoader.parse_skill_file(md_file)
                tools.extend(file_tools)
                logger.info(f"Loaded {len(file_tools)} tools from {md_file.name}")
            except Exception as e:
                logger.error(f"Error parsing {md_file.name}: {e}")

        logger.info(f"SkillLoader: total {len(tools)} tools from {path}")
        return tools

    @staticmethod
    def parse_skill_file(path: Path) -> List[SkillTool]:
        """
        Parse a single SKILL.md file into SkillTool list.

        Expected format:
        ```
        # Skill: <Skill Name>
        ## Agent: <agent_name>
        ## Risk: <default_risk>
        ## Category: <category>
        ### Tools
        #### <tool_name>
        - Description: ...
        - Parameters:
          - param_name (type, required/optional): description
        - Risk: <override_risk>
        - Requires Approval: yes/no
        ```
        """
        content = path.read_text(encoding="utf-8")
        tools = []

        # Extract top-level metadata
        default_agent = SkillLoader._extract_field(content, r"^##\s*Agent:\s*(.+)", "")
        default_risk = SkillLoader._extract_field(content, r"^##\s*Risk:\s*(\w+)", "low")
        category = SkillLoader._extract_field(content, r"^##\s*Category:\s*(.+)", path.stem)

        # Split into tool sections (#### tool_name)
        tool_sections = re.split(r"^####\s+", content, flags=re.MULTILINE)[1:]

        for section in tool_sections:
            lines = section.strip().split("\n")
            tool_name = lines[0].strip()
            section_text = "\n".join(lines[1:])

            # Parse tool metadata
            description = SkillLoader._extract_field(
                section_text, r"-\s*Description:\s*(.+)", f"Tool: {tool_name}"
            )
            risk = SkillLoader._extract_field(
                section_text, r"-\s*Risk:\s*(\w+)", default_risk
            )
            requires_approval_str = SkillLoader._extract_field(
                section_text, r"-\s*Requires Approval:\s*(\w+)", "no"
            )
            requires_approval = requires_approval_str.lower() in ("yes", "true", "1")

            # Parse parameters
            parameters = SkillLoader._parse_parameters(section_text)

            # Parse examples
            examples = SkillLoader._parse_examples(section_text)

            tool = SkillTool(
                name=tool_name,
                description=description,
                input_schema=parameters,
                server_name="",
                agent=default_agent,
                risk_level=risk,
                requires_approval=requires_approval,
                category=category,
                examples=examples,
            )
            tools.append(tool)

        return tools

    @staticmethod
    def _extract_field(text: str, pattern: str, default: str = "") -> str:
        """Extract a single field from text using regex."""
        match = re.search(pattern, text, re.MULTILINE)
        return match.group(1).strip() if match else default

    @staticmethod
    def _parse_parameters(text: str) -> Dict[str, Any]:
        """
        Parse parameter list into JSON Schema format.

        Input format:
          - param_name (type, required): description
          - param_name (type, enum: a|b|c, default: x): description
        """
        schema = {"type": "object", "properties": {}, "required": []}

        # Find Parameters section
        params_match = re.search(
            r"-\s*Parameters:\s*\n((?:\s+-\s+.+\n?)+)", text
        )
        if not params_match:
            return schema

        params_text = params_match.group(1)
        # Match individual parameters
        param_pattern = re.compile(
            r"\s+-\s+(\w+)\s*\(([^)]+)\)(?::\s*(.+))?",
            re.MULTILINE,
        )

        for match in param_pattern.finditer(params_text):
            param_name = match.group(1)
            param_meta = match.group(2)
            param_desc = match.group(3).strip() if match.group(3) else ""

            # Parse type
            param_type = "string"
            type_match = re.search(r"(string|integer|boolean|number|array|object)", param_meta)
            if type_match:
                param_type = type_match.group(1)

            prop: Dict[str, Any] = {
                "type": param_type,
            }
            if param_desc:
                prop["description"] = param_desc

            # Parse enum
            enum_match = re.search(r"enum:\s*([\w|]+)", param_meta)
            if enum_match:
                prop["enum"] = enum_match.group(1).split("|")

            # Parse default
            default_match = re.search(r"default:\s*(\S+)", param_meta)
            if default_match:
                default_val = default_match.group(1)
                # Type-cast default
                if param_type == "boolean":
                    prop["default"] = default_val.lower() in ("true", "1", "yes")
                elif param_type == "integer":
                    prop["default"] = int(default_val)
                else:
                    prop["default"] = default_val

            schema["properties"][param_name] = prop

            # Check required
            if "required" in param_meta.lower():
                schema["required"].append(param_name)

        return schema

    @staticmethod
    def _parse_examples(text: str) -> List[Dict]:
        """Parse Examples section (Input/Output pairs)."""
        examples = []
        # Find example blocks
        example_pattern = re.compile(
            r"-\s*Input:\s*({.+?})\s*\n\s*-\s*Output:\s*({.+?})",
            re.MULTILINE | re.DOTALL,
        )
        for match in example_pattern.finditer(text):
            try:
                import json
                examples.append({
                    "input": json.loads(match.group(1)),
                    "output": json.loads(match.group(2)),
                })
            except (json.JSONDecodeError, ValueError):
                pass
        return examples
