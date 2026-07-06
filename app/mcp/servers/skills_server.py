# app/mcp/servers/skills_server.py
"""
Skills MCP Server — exposes higher-level agent skills via MCP.
Skills = composite workflows (e.g., "setup gaming server", "onboard team").
Phase 2: Load custom skills from DB/files.
"""
import logging
from typing import Dict, Any, List

from app.mcp.server import MCPServer
from app.mcp.protocol import (
    ToolDefinition,
    ToolCallRequest,
    ToolCallResponse,
    ServerInfo,
)

logger = logging.getLogger(__name__)


class SkillsMCPServer(MCPServer):
    """MCP Server for composite skills (multi-step workflows)."""

    def __init__(self):
        self._skills: Dict[str, Dict[str, Any]] = {}

    @property
    def info(self) -> ServerInfo:
        return ServerInfo(
            name="skills",
            version="1.0.0",
            description="Composite skills — multi-step workflows for common tasks.",
            tool_count=len(self._skills),
        )

    def register_skill(self, name: str, description: str, parameters: Dict, handler) -> None:
        """Register a composite skill."""
        self._skills[name] = {
            "description": description,
            "parameters": parameters,
            "handler": handler,
        }

    def list_tools(self) -> List[ToolDefinition]:
        return [
            ToolDefinition(
                name=name,
                description=skill["description"],
                input_schema=skill["parameters"],
                server_name="skills",
            )
            for name, skill in self._skills.items()
        ]

    async def call_tool(self, request: ToolCallRequest) -> ToolCallResponse:
        """Execute a composite skill."""
        skill = self._skills.get(request.tool_name)
        if not skill:
            return ToolCallResponse(
                id=request.id,
                success=False,
                error=f"Skill not found: {request.tool_name}",
            )

        try:
            args = dict(request.arguments)
            args.pop("_context", None)
            result = await skill["handler"](**args)
            return ToolCallResponse(
                id=request.id,
                success=True,
                result=result if isinstance(result, dict) else {"result": str(result)},
            )
        except Exception as e:
            return ToolCallResponse(
                id=request.id,
                success=False,
                error=str(e),
            )
