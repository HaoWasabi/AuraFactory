"""Discord Connectors Package — SPEC v2.

Entry point: DiscordConnector (facade that aggregates all sub-connectors).
"""

from app.connectors.discord.connector import DiscordConnector

__all__ = ["DiscordConnector"]
