"""
Connectors — External service integrations for AuraFactory.

Each connector provides a clean async interface to an external service.
Currently implemented:
- discord: Full Discord guild management (channels, roles, members, etc.)
"""

from app.connectors.base import BaseConnector

__all__ = ["BaseConnector"]
