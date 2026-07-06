# app/skills/startup.py
"""
Skills startup — initializes SkillRegistry at app boot.
Called from app/main.py during startup sequence.
Phase 1: Load from MCP + .md files.
Phase 2: Also load custom skills from DB.
"""
import logging
from typing import Optional

from app.mcp.client import MCPClient
from app.skills.registry import SkillRegistry
from app.skills.loader import SkillLoader
from app.skills.validator import SkillValidator

logger = logging.getLogger(__name__)

# Global singleton
_registry: Optional[SkillRegistry] = None
_validator: Optional[SkillValidator] = None


def init_skills(mcp_client: MCPClient, skills_dir: str = "./skills") -> SkillRegistry:
    """
    Initialize the Skills Registry at app startup.

    Strategy:
    1. Load tool definitions from .md files (authoritative source)
    2. Cross-reference with MCP tools (runtime validation)
    3. Build validator

    Args:
        mcp_client: Initialized MCPClient with servers registered
        skills_dir: Path to skills/ directory with .md definitions

    Returns:
        Initialized SkillRegistry
    """
    global _registry, _validator

    # Create registry backed by MCP
    registry = SkillRegistry(mcp_client)

    # Load from MCP servers (runtime tools)
    registry.load()

    # Also load from .md definitions (enriches with metadata)
    skill_tools = SkillLoader.load_directory(skills_dir)
    if skill_tools:
        # Merge: .md definitions override MCP metadata (risk, agent, examples)
        for tool in skill_tools:
            existing = registry.get_tool(tool.name)
            if existing:
                # Update metadata from .md (MCP tool already has schema)
                existing.agent = tool.agent
                existing.risk_level = tool.risk_level
                existing.requires_approval = tool.requires_approval
                existing.category = tool.category
                existing.examples = tool.examples
            else:
                # Tool defined in .md but not yet in MCP — register anyway
                # (useful for planning before implementation)
                registry._tools[tool.name] = tool

        logger.info(f"Merged {len(skill_tools)} skill definitions from {skills_dir}")

    # Build validator
    _validator = SkillValidator(registry)
    _registry = registry

    summary = registry.get_tool_summary()
    logger.info(
        f"Skills ready: {summary['total_tools']} tools, "
        f"agents={summary['by_agent']}, "
        f"approval_required={len(summary['approval_required'])}"
    )

    return registry


def get_registry() -> SkillRegistry:
    """Get the global SkillRegistry instance."""
    if _registry is None:
        raise RuntimeError("SkillRegistry not initialized. Call init_skills() first.")
    return _registry


def get_validator() -> SkillValidator:
    """Get the global SkillValidator instance."""
    if _validator is None:
        raise RuntimeError("SkillValidator not initialized. Call init_skills() first.")
    return _validator
