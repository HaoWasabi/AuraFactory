# app/connectors/health.py
"""Shared health check utilities for connectors."""
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


async def check_connector_health(connector) -> Dict[str, Any]:
    """Run health check on a connector and return status."""
    try:
        is_healthy = await connector.health_check()
        return {
            "connector": connector.name,
            "status": "healthy" if is_healthy else "unhealthy",
            "tools_count": len(connector.tools),
        }
    except Exception as e:
        return {
            "connector": connector.name,
            "status": "error",
            "error": str(e),
        }
