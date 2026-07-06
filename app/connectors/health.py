"""
Health Check Helper — System health verification for AuraFactory.

Provides a unified health check that verifies:
- Database connectivity
- Bot status (connected, latency)
- MCP server availability
- Memory service status
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import nextcord

logger = logging.getLogger(__name__)


@dataclass
class HealthStatus:
    """Result of a health check."""

    healthy: bool = True
    checks: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    @property
    def unhealthy_checks(self) -> List[str]:
        """Return names of failing checks."""
        return [
            name
            for name, status in self.checks.items()
            if not status.get("healthy", False)
        ]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a dict."""
        return {
            "healthy": self.healthy,
            "checks": self.checks,
            "timestamp": self.timestamp,
            "unhealthy": self.unhealthy_checks,
        }


async def check_bot_health(bot: Optional[nextcord.Bot]) -> Dict[str, Any]:
    """Check Discord bot health.

    Args:
        bot: The nextcord bot instance.

    Returns:
        Health status dict.
    """
    if bot is None:
        return {"healthy": False, "error": "Bot instance is None"}

    if bot.is_closed():
        return {"healthy": False, "error": "Bot connection is closed"}

    if not bot.is_ready():
        return {"healthy": False, "error": "Bot is not ready"}

    return {
        "healthy": True,
        "latency_ms": round(bot.latency * 1000, 2),
        "guild_count": len(bot.guilds),
        "user": str(bot.user),
    }


async def check_database_health(db: Optional[Any]) -> Dict[str, Any]:
    """Check database connectivity.

    Args:
        db: Database connection or engine.

    Returns:
        Health status dict.
    """
    if db is None:
        return {"healthy": False, "error": "Database not configured"}

    try:
        # Attempt a simple query — implementation depends on DB driver
        if hasattr(db, "execute"):
            start = time.time()
            await db.execute("SELECT 1")
            latency = (time.time() - start) * 1000
            return {"healthy": True, "latency_ms": round(latency, 2)}
        elif hasattr(db, "ping"):
            start = time.time()
            await db.ping()
            latency = (time.time() - start) * 1000
            return {"healthy": True, "latency_ms": round(latency, 2)}
        else:
            return {"healthy": True, "note": "DB exists but ping not supported"}
    except Exception as exc:
        return {"healthy": False, "error": str(exc)}


async def check_mcp_health(mcp_client: Optional[Any]) -> Dict[str, Any]:
    """Check MCP client/server health.

    Args:
        mcp_client: The MCPClient instance.

    Returns:
        Health status dict.
    """
    if mcp_client is None:
        return {"healthy": False, "error": "MCP client not configured"}

    try:
        tool_count = len(mcp_client.list_all_tools())
        server_count = len(mcp_client.server_names)
        return {
            "healthy": True,
            "servers": server_count,
            "tools": tool_count,
            "server_names": mcp_client.server_names,
        }
    except Exception as exc:
        return {"healthy": False, "error": str(exc)}


async def check_memory_health(memory_service: Optional[Any]) -> Dict[str, Any]:
    """Check memory service health.

    Args:
        memory_service: The MemoryService instance.

    Returns:
        Health status dict.
    """
    if memory_service is None:
        return {"healthy": False, "error": "Memory service not configured"}

    try:
        if hasattr(memory_service, "health_check"):
            result = await memory_service.health_check()
            return {"healthy": True, **result}
        return {"healthy": True, "note": "Memory service exists"}
    except Exception as exc:
        return {"healthy": False, "error": str(exc)}


async def run_health_check(
    bot: Optional[nextcord.Bot] = None,
    db: Optional[Any] = None,
    mcp_client: Optional[Any] = None,
    memory_service: Optional[Any] = None,
) -> HealthStatus:
    """Run a full health check across all components.

    Args:
        bot: Discord bot instance.
        db: Database connection.
        mcp_client: MCP client instance.
        memory_service: Memory service instance.

    Returns:
        HealthStatus with all check results.
    """
    status = HealthStatus()

    # Run all checks
    status.checks["bot"] = await check_bot_health(bot)
    status.checks["database"] = await check_database_health(db)
    status.checks["mcp"] = await check_mcp_health(mcp_client)
    status.checks["memory"] = await check_memory_health(memory_service)

    # Overall health is True only if all checks pass
    status.healthy = all(
        check.get("healthy", False)
        for check in status.checks.values()
    )

    if not status.healthy:
        logger.warning(
            "Health check failed. Unhealthy: %s",
            status.unhealthy_checks,
        )
    else:
        logger.debug("Health check passed. All systems operational.")

    return status
