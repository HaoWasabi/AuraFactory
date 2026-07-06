# app/connectors/__init__.py
"""
Layer 5 — External Connectors.
All external API wrappers expose via ConnectorBase ABC.
"""
from app.connectors.base import ConnectorBase

__all__ = ["ConnectorBase"]
