# app/skills/registry.py
"""
Skill Registry — central registry for agent tool discovery and planning.
Wraps MCPClient to provide agent-aware, risk-filtered tool lists.
Agents query this for available actions; Orchestrator uses it for planning.
"""
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, field

from app.mcp.client import MCPClient
from app.mcp.protocol import ToolDefinition
from app.agents.contracts import AgentRole

logger = logging.getLogger(__name__)


# ============================================================
# Enriched Tool Definition (adds agent/risk metadata)
# ============================================================

@dataclass
class SkillTool:
    """Tool definition enriched with routing metadata."""
    name: str
    description: str
    input_schema: Dict
    server_name: str = ""
    # Routing metadata
    agent: str = ""                  # Which agent owns this tool
    risk_level: str = "low"          # low | medium | high | critical
    requires_approval: bool = False  # HITL gate?
    category: str = ""               # Grouping (channels, roles, etc.)
    examples: List[Dict] = field(default_factory=list)

    @classmethod
    def from_mcp_tool(cls, tool: ToolDefinition, **metadata) -> "SkillTool":
        """Create from MCP ToolDefinition + optional metadata."""
        return cls(
            name=tool.name,
            description=tool.description,
            input_schema=tool.input_schema,
            server_name=tool.server_name,
            **metadata,
        )

    def to_planning_format(self) -> Dict:
        """Compact format for LLM planning prompts."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_schema.get("properties", {}),
            "required": self.input_schema.get("required", []),
            "risk": self.risk_level,
            "agent": self.agent,
        }


# ============================================================
# Risk Matrix — maps tool names to risk levels
# ============================================================

RISK_MATRIX: Dict[str, str] = {
    # Critical — irreversible, server-wide impact
    "delete_channel": "high",
    "delete_role": "high",
    "ban_member": "high",
    "kick_member": "high",
    "backup_server": "medium",
    # Medium — modifying actions
    "create_channel": "medium",
    "edit_channel": "medium",
    "create_role": "medium",
    "assign_role": "medium",
    "create_category": "medium",
    "create_webhook": "medium",
    "create_automod_rule": "medium",
    "send_webhook_message": "medium",
    # Low — read-only
    "list_channels": "low",
    "list_members": "low",
    "get_guild_info": "low",
}

APPROVAL_REQUIRED = {"delete_channel", "ban_member", "kick_member", "delete_role"}

# Tool → Agent routing
AGENT_ROUTING: Dict[str, str] = {
    # Architect — all write/modify operations
    "create_channel": "architect",
    "delete_channel": "architect",
    "edit_channel": "architect",
    "create_role": "architect",
    "delete_role": "architect",
    "assign_role": "architect",
    "create_category": "architect",
    "create_webhook": "architect",
    "send_webhook_message": "architect",
    "create_automod_rule": "architect",
    "backup_server": "architect",
    "kick_member": "architect",
    "ban_member": "architect",
    # Assistant — read-only + info
    "list_channels": "assistant",
    "list_members": "assistant",
    "get_guild_info": "assistant",
}


# ============================================================
# SkillRegistry
# ============================================================

class SkillRegistry:
    """
    Central Skills Registry.
    - Discovers tools from MCPClient
    - Enriches with risk/agent metadata
    - Provides filtered views for planning and execution
    - Validates tool calls before passing to MCP
    """

    def __init__(self, mcp_client: MCPClient):
        self._mcp = mcp_client
        self._tools: Dict[str, SkillTool] = {}
        self._loaded = False

    def load(self) -> None:
        """Load tools from MCP and enrich with metadata."""
        mcp_tools = self._mcp.list_tools()

        for tool in mcp_tools:
            skill_tool = SkillTool.from_mcp_tool(
                tool,
                agent=AGENT_ROUTING.get(tool.name, ""),
                risk_level=RISK_MATRIX.get(tool.name, "low"),
                requires_approval=tool.name in APPROVAL_REQUIRED,
            )
            self._tools[tool.name] = skill_tool

        self._loaded = True
        logger.info(f"SkillRegistry loaded {len(self._tools)} tools from MCP")

    def load_from_definitions(self, skill_tools: List[SkillTool]) -> None:
        """Load from pre-parsed SkillTool list (from .md files)."""
        for tool in skill_tools:
            self._tools[tool.name] = tool
        self._loaded = True
        logger.info(f"SkillRegistry loaded {len(skill_tools)} tools from definitions")

    # ── Query API ──────────────────────────────────────────────

    def get_tool(self, name: str) -> Optional[SkillTool]:
        """Get a single tool by name."""
        return self._tools.get(name)

    def get_all_tools(self) -> List[SkillTool]:
        """Get all registered tools."""
        return list(self._tools.values())

    def get_tools_for_agent(self, agent_role: AgentRole) -> List[SkillTool]:
        """Get tools available to a specific agent."""
        role_name = agent_role.value
        return [t for t in self._tools.values() if t.agent == role_name]

    def get_tools_by_risk(self, max_risk: str = "medium") -> List[SkillTool]:
        """Get tools up to a certain risk level."""
        risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        max_level = risk_order.get(max_risk, 1)
        return [
            t for t in self._tools.values()
            if risk_order.get(t.risk_level, 0) <= max_level
        ]

    def get_tools_by_category(self, category: str) -> List[SkillTool]:
        """Get tools in a specific category."""
        return [t for t in self._tools.values() if t.category == category]

    # ── Planning API (for Orchestrator) ────────────────────────

    def get_planning_context(self, agent_role: Optional[AgentRole] = None) -> List[Dict]:
        """
        Get tool list formatted for LLM planning.
        If agent_role given, filter to that agent's tools only.
        """
        tools = self.get_tools_for_agent(agent_role) if agent_role else self.get_all_tools()
        return [t.to_planning_format() for t in tools]

    def get_tool_summary(self) -> Dict:
        """Get summary stats for system prompt injection."""
        by_agent = {}
        by_risk = {"low": 0, "medium": 0, "high": 0, "critical": 0}

        for tool in self._tools.values():
            agent = tool.agent or "unassigned"
            by_agent[agent] = by_agent.get(agent, 0) + 1
            by_risk[tool.risk_level] = by_risk.get(tool.risk_level, 0) + 1

        return {
            "total_tools": len(self._tools),
            "by_agent": by_agent,
            "by_risk": by_risk,
            "approval_required": [t.name for t in self._tools.values() if t.requires_approval],
        }

    # ── Execution API ──────────────────────────────────────────

    def requires_approval(self, tool_name: str) -> bool:
        """Check if a tool requires HITL approval."""
        tool = self._tools.get(tool_name)
        return tool.requires_approval if tool else False

    def get_risk_level(self, tool_name: str) -> str:
        """Get risk level for a tool."""
        tool = self._tools.get(tool_name)
        return tool.risk_level if tool else "unknown"

    def tool_exists(self, tool_name: str) -> bool:
        """Check if tool is registered."""
        return tool_name in self._tools

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    @property
    def is_loaded(self) -> bool:
        return self._loaded
