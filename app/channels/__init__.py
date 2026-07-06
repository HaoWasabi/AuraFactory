# app/channels/__init__.py
"""
Layer 1 — Channel Adapters.
Adapts incoming messages from different platforms to standardized format.
"""
from app.channels.base import ChannelAdapterBase

__all__ = ["ChannelAdapterBase"]
