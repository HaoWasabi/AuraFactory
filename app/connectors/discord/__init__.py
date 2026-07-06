"""
Discord Connectors — All sub-connectors for Discord guild operations.

This package provides 15 connector classes + 1 facade (DiscordConnector).
Each connector handles a specific domain of Discord operations.
"""

from app.connectors.discord.automod import AutomodConnector
from app.connectors.discord.backup import BackupConnector
from app.connectors.discord.categories import CategoriesConnector
from app.connectors.discord.channels import ChannelsConnector
from app.connectors.discord.connector import DiscordConnector
from app.connectors.discord.emojis import EmojisConnector
from app.connectors.discord.features import FeaturesConnector
from app.connectors.discord.guild import GuildConnector
from app.connectors.discord.invites import InvitesConnector
from app.connectors.discord.members import MembersConnector
from app.connectors.discord.onboarding import OnboardingConnector
from app.connectors.discord.permissions import PermissionsConnector
from app.connectors.discord.roles import RolesConnector
from app.connectors.discord.templates import TemplatesConnector
from app.connectors.discord.threads import ThreadsConnector
from app.connectors.discord.webhooks import WebhooksConnector

__all__ = [
    "AutomodConnector",
    "BackupConnector",
    "CategoriesConnector",
    "ChannelsConnector",
    "DiscordConnector",
    "EmojisConnector",
    "FeaturesConnector",
    "GuildConnector",
    "InvitesConnector",
    "MembersConnector",
    "OnboardingConnector",
    "PermissionsConnector",
    "RolesConnector",
    "TemplatesConnector",
    "ThreadsConnector",
    "WebhooksConnector",
]
