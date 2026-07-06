# app/mcp/servers/discord_server.py
"""
Discord MCP Server — exposes all Discord tools via MCP protocol.
Wraps app/connectors/discord/* modules.
"""
import logging
from typing import Dict, Any, List

from app.mcp.server import MCPServer
from app.mcp.protocol import (
    ToolDefinition,
    ToolCallRequest,
    ToolCallResponse,
    ServerInfo,
)

logger = logging.getLogger(__name__)


class DiscordMCPServer(MCPServer):
    """MCP Server for Discord tools (channels, roles, members, etc.)."""

    def __init__(self, bot=None):
        """
        Args:
            bot: nextcord.Bot instance (needed for Discord API calls)
        """
        self._bot = bot
        self._tool_handlers: Dict[str, Any] = {}
        self._tool_defs: List[ToolDefinition] = []
        self._load_tools()

    @property
    def info(self) -> ServerInfo:
        return ServerInfo(
            name="discord",
            version="1.0.0",
            description="Discord server management tools — channels, roles, members, moderation, webhooks.",
            tool_count=len(self._tool_defs),
        )

    def _load_tools(self) -> None:
        """Load tool definitions from connector modules."""
        # Import tool modules (graceful — skip if any fail)
        try:
            from app.connectors.discord import channels, roles, members
            from app.connectors.discord import categories, threads, webhooks
            from app.connectors.discord import permissions, invites, emojis
            from app.connectors.discord import guild, features, automod
            from app.connectors.discord import backup, onboarding, templates
        except ImportError as e:
            logger.error(f"Discord connector import error: {e}")
            # Try minimal imports
            try:
                from app.connectors.discord import channels, roles, members
                from app.connectors.discord import categories, guild, backup
            except ImportError as e2:
                logger.error(f"Discord connector critical import error: {e2}")
                return

        # Map tool_name → (module, function_name, schema)
        tool_registry = [
            # --- Channels ---
            ("create_channel", channels, "create_channel", {
                "type": "object",
                "properties": {
                    "guild_id": {"type": "integer", "description": "Target guild ID"},
                    "name": {"type": "string", "description": "Channel name"},
                    "channel_type": {"type": "string", "enum": ["text", "voice", "forum", "stage"], "description": "Channel type"},
                    "category": {"type": "string", "description": "Category name to place under"},
                    "topic": {"type": "string", "description": "Channel topic"},
                },
                "required": ["guild_id", "name"],
            }),
            ("delete_channel", channels, "delete_channel", {
                "type": "object",
                "properties": {
                    "guild_id": {"type": "integer"},
                    "channel_name": {"type": "string", "description": "Channel name to delete"},
                },
                "required": ["guild_id", "channel_name"],
            }),
            ("edit_channel", channels, "edit_channel", {
                "type": "object",
                "properties": {
                    "guild_id": {"type": "integer"},
                    "channel_name": {"type": "string"},
                    "new_name": {"type": "string"},
                    "new_topic": {"type": "string"},
                    "slowmode": {"type": "integer", "description": "Slowmode in seconds"},
                },
                "required": ["guild_id", "channel_name"],
            }),
            ("list_channels", channels, "list_channels", {
                "type": "object",
                "properties": {
                    "guild_id": {"type": "integer"},
                    "channel_type": {"type": "string", "enum": ["text", "voice", "all"]},
                },
                "required": ["guild_id"],
            }),
            # --- Roles ---
            ("create_role", roles, "create_role", {
                "type": "object",
                "properties": {
                    "guild_id": {"type": "integer"},
                    "name": {"type": "string", "description": "Role name"},
                    "color": {"type": "string", "description": "Hex color code"},
                    "permissions": {"type": "array", "items": {"type": "string"}},
                    "mentionable": {"type": "boolean"},
                    "hoist": {"type": "boolean", "description": "Show separately in member list"},
                },
                "required": ["guild_id", "name"],
            }),
            ("delete_role", roles, "delete_role", {
                "type": "object",
                "properties": {
                    "guild_id": {"type": "integer"},
                    "role_name": {"type": "string"},
                },
                "required": ["guild_id", "role_name"],
            }),
            ("assign_role", roles, "assign_role", {
                "type": "object",
                "properties": {
                    "guild_id": {"type": "integer"},
                    "user_id": {"type": "integer"},
                    "role_name": {"type": "string"},
                },
                "required": ["guild_id", "user_id", "role_name"],
            }),
            # --- Members ---
            ("kick_member", members, "kick_member", {
                "type": "object",
                "properties": {
                    "guild_id": {"type": "integer"},
                    "user_id": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["guild_id", "user_id"],
            }),
            ("ban_member", members, "ban_member", {
                "type": "object",
                "properties": {
                    "guild_id": {"type": "integer"},
                    "user_id": {"type": "integer"},
                    "reason": {"type": "string"},
                    "delete_days": {"type": "integer", "description": "Days of messages to delete (0-7)"},
                },
                "required": ["guild_id", "user_id"],
            }),
            ("list_members", members, "list_members", {
                "type": "object",
                "properties": {
                    "guild_id": {"type": "integer"},
                    "limit": {"type": "integer", "description": "Max members to return"},
                },
                "required": ["guild_id"],
            }),
            # --- Categories ---
            ("create_category", categories, "create_category", {
                "type": "object",
                "properties": {
                    "guild_id": {"type": "integer"},
                    "name": {"type": "string"},
                },
                "required": ["guild_id", "name"],
            }),
            # --- Webhooks ---
            ("create_webhook", webhooks, "create_webhook", {
                "type": "object",
                "properties": {
                    "guild_id": {"type": "integer"},
                    "channel_name": {"type": "string"},
                    "webhook_name": {"type": "string"},
                },
                "required": ["guild_id", "channel_name", "webhook_name"],
            }),
            ("send_webhook_message", webhooks, "send_webhook_message", {
                "type": "object",
                "properties": {
                    "webhook_url": {"type": "string"},
                    "content": {"type": "string"},
                    "username": {"type": "string"},
                    "embed": {"type": "object"},
                },
                "required": ["webhook_url", "content"],
            }),
            # --- Automod ---
            ("create_automod_rule", automod, "create_automod_rule", {
                "type": "object",
                "properties": {
                    "guild_id": {"type": "integer"},
                    "name": {"type": "string"},
                    "trigger_type": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["guild_id", "name", "trigger_type"],
            }),
            # --- Guild ---
            ("get_guild_info", guild, "get_guild_info", {
                "type": "object",
                "properties": {
                    "guild_id": {"type": "integer"},
                },
                "required": ["guild_id"],
            }),
            # --- Backup ---
            ("backup_server", backup, "backup_server", {
                "type": "object",
                "properties": {
                    "guild_id": {"type": "integer"},
                    "include_messages": {"type": "boolean"},
                },
                "required": ["guild_id"],
            }),
        ]

        for tool_name, module, func_name, schema in tool_registry:
            handler = None
            # Try 1: direct function on module
            handler = getattr(module, func_name, None)
            # Try 2: look inside classes in the module (class-based connectors)
            if handler is None:
                for attr_name in dir(module):
                    obj = getattr(module, attr_name, None)
                    if isinstance(obj, type):  # It's a class
                        method = getattr(obj, func_name, None)
                        if method and callable(method):
                            # Use staticmethod or classmethod directly
                            handler = method
                            break
            if handler is None:
                logger.debug(f"Tool handler not found: {func_name} in {module.__name__}")

            if handler:
                self._tool_handlers[tool_name] = handler
                self._tool_defs.append(ToolDefinition(
                    name=tool_name,
                    description=handler.__doc__ or f"Discord tool: {tool_name}",
                    input_schema=schema,
                    server_name="discord",
                ))

    def list_tools(self) -> List[ToolDefinition]:
        return self._tool_defs

    async def call_tool(self, request: ToolCallRequest) -> ToolCallResponse:
        """Execute a Discord tool."""
        handler = self._tool_handlers.get(request.tool_name)
        if not handler:
            return ToolCallResponse(
                id=request.id,
                success=False,
                error=f"Unknown tool: {request.tool_name}",
            )

        # Extract context
        args = dict(request.arguments)
        ctx = args.pop("_context", {})
        guild = ctx.get("guild") or self._get_guild(args.get("guild_id"))

        if not guild:
            return ToolCallResponse(
                id=request.id,
                success=False,
                error=f"Guild not found: {args.get('guild_id')}",
            )

        try:
            result = await handler(guild=guild, **args)
            return ToolCallResponse(
                id=request.id,
                success=True,
                result=result if isinstance(result, dict) else {"message": str(result)},
            )
        except Exception as e:
            return ToolCallResponse(
                id=request.id,
                success=False,
                error=str(e),
            )

    def _get_guild(self, guild_id: int):
        """Get guild object from bot cache."""
        if self._bot and guild_id:
            return self._bot.get_guild(guild_id)
        return None
