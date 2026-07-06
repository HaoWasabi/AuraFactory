"""
Skills MCP Server — Exposes skill registry operations as MCP tools.

Tools:
- skills.list: List all available skills (optionally filtered).
- skills.get_by_category: Get skills in a specific category.
- skills.validate_params: Validate parameters against a skill's schema.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.mcp.protocol import ToolDefinition
from app.mcp.server import MCPServer

logger = logging.getLogger(__name__)


class SkillsMCPServer(MCPServer):
    """MCP server for skill registry queries.

    Provides read-only access to the skill registry so agents
    can discover what tools/skills are available.
    """

    def __init__(self, skill_registry: Any = None) -> None:
        super().__init__()
        self._skill_registry = skill_registry
        self._register_tools()

    def set_skill_registry(self, skill_registry: Any) -> None:
        """Inject the skill registry (can be set after construction)."""
        self._skill_registry = skill_registry

    def _get_registry(self) -> Any:
        """Get skill registry or raise if not configured."""
        if self._skill_registry is None:
            raise RuntimeError(
                "SkillRegistry not configured. Call set_skill_registry() first."
            )
        return self._skill_registry

    # ------------------------------------------------------------------
    # Tool Registration
    # ------------------------------------------------------------------

    def _register_tools(self) -> None:
        """Register all skills tools."""

        # skills.list
        self.register_tool(
            ToolDefinition(
                name="skills.list",
                description=(
                    "List all available skills in the registry. "
                    "Optionally filter by risk level or search term."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "search": {
                            "type": "string",
                            "description": "Optional search term to filter skills.",
                        },
                        "max_risk": {
                            "type": "string",
                            "description": "Max risk level filter (low|medium|high|critical).",
                        },
                    },
                },
                risk_level="low",
            ),
            self._handle_list,
        )

        # skills.get_by_category
        self.register_tool(
            ToolDefinition(
                name="skills.get_by_category",
                description=(
                    "Get all skills belonging to a specific category "
                    "(e.g. 'moderation', 'management', 'information')."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": "The category name to filter by.",
                        },
                    },
                    "required": ["category"],
                },
                risk_level="low",
            ),
            self._handle_get_by_category,
        )

        # skills.validate_params
        self.register_tool(
            ToolDefinition(
                name="skills.validate_params",
                description=(
                    "Validate a set of parameters against a skill's schema. "
                    "Returns validation result with any errors."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "skill_name": {
                            "type": "string",
                            "description": "The skill/tool name to validate against.",
                        },
                        "params": {
                            "type": "object",
                            "description": "The parameters to validate.",
                        },
                    },
                    "required": ["skill_name", "params"],
                },
                risk_level="low",
            ),
            self._handle_validate_params,
        )

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_list(
        self,
        search: Optional[str] = None,
        max_risk: Optional[str] = None,
    ) -> dict:
        registry = self._get_registry()
        skills = await registry.list_skills(search=search, max_risk=max_risk)
        return {"skills": skills, "count": len(skills)}

    async def _handle_get_by_category(self, category: str) -> dict:
        registry = self._get_registry()
        skills = await registry.get_by_category(category=category)
        return {"category": category, "skills": skills, "count": len(skills)}

    async def _handle_validate_params(self, skill_name: str, params: dict) -> dict:
        registry = self._get_registry()
        result = await registry.validate_params(skill_name=skill_name, params=params)
        return result

    # ------------------------------------------------------------------
    # MCPServer interface
    # ------------------------------------------------------------------

    def get_server_name(self) -> str:
        return "skills"
