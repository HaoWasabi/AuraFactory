"""Skill startup — loads all skill files and populates the registry.

Called at application boot to initialize the complete skill registry
from all .md files in the skills/ directory.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.skills.loader import SkillLoader
from app.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


def init_skills(skills_dir: str) -> SkillRegistry:
    """Load all skill .md files from directory and return populated registry.

    Scans the specified directory for .md skill definition files,
    parses each one, and registers all tools into a single registry.

    Args:
        skills_dir: Path to the skills/ directory containing .md files.

    Returns:
        Fully populated SkillRegistry instance.

    Raises:
        FileNotFoundError: If skills_dir does not exist.
    """
    skills_path = Path(skills_dir)
    if not skills_path.exists():
        raise FileNotFoundError(f"Skills directory not found: {skills_dir}")

    if not skills_path.is_dir():
        raise ValueError(f"Skills path is not a directory: {skills_dir}")

    registry = SkillRegistry()
    loader = SkillLoader()

    # Find all .md files
    md_files = sorted(skills_path.glob("*.md"))
    if not md_files:
        logger.warning("No .md skill files found in %s", skills_dir)
        return registry

    logger.info("Loading skills from %s (%d files)", skills_dir, len(md_files))

    loaded_count = 0
    error_count = 0

    for md_file in md_files:
        try:
            tools = loader.load_skill_file(str(md_file))
            for tool in tools:
                registry.register_skill(tool)
                loaded_count += 1
        except Exception as exc:
            logger.error("Failed to load skill file %s: %s", md_file.name, exc)
            error_count += 1

    logger.info(
        "Skills initialization complete: %d tools loaded from %d files (%d errors)",
        loaded_count,
        len(md_files) - error_count,
        error_count,
    )

    # Log summary by agent role
    for role in ("admin", "assistant", "fast_track"):
        role_tools = registry.get_tools_for_agent(role)
        if role_tools:
            logger.info("  Agent '%s': %d tools", role, len(role_tools))

    # Log summary by risk level
    for risk in ("low", "medium", "high", "critical"):
        risk_tools = registry.get_tools_by_risk(risk)
        logger.debug("  Risk <= '%s': %d tools", risk, len(risk_tools))

    return registry
