# app/mcp/servers/memory_server.py
"""
Memory MCP Server — exposes memory operations (recall, store, search) via MCP.
Wraps app/memory/service.py.
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


class MemoryMCPServer(MCPServer):
    """MCP Server for memory operations — recall, store, search."""

    def __init__(self, memory_service=None):
        """
        Args:
            memory_service: MemoryService instance from app.memory.service
        """
        self._memory = memory_service

    @property
    def info(self) -> ServerInfo:
        return ServerInfo(
            name="memory",
            version="1.0.0",
            description="Long-term memory — recall facts, store new memories, semantic search.",
            tool_count=5,
        )

    def list_tools(self) -> List[ToolDefinition]:
        return [
            ToolDefinition(
                name="memory_recall",
                description="Recall relevant memories for a query. Returns semantic facts and recent messages.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "What to recall"},
                        "guild_id": {"type": "integer", "description": "Guild context"},
                        "session_id": {"type": "string", "description": "Session context"},
                        "top_k": {"type": "integer", "description": "Max results", "default": 5},
                    },
                    "required": ["query"],
                },
                server_name="memory",
            ),
            ToolDefinition(
                name="memory_store",
                description="Store a new fact or observation in long-term memory.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "Fact to remember"},
                        "fact_type": {"type": "string", "enum": ["preference", "fact", "event", "skill"], "description": "Type of memory"},
                        "importance": {"type": "number", "description": "0.0-1.0 importance score"},
                        "guild_id": {"type": "integer"},
                    },
                    "required": ["content"],
                },
                server_name="memory",
            ),
            ToolDefinition(
                name="memory_add_message",
                description="Add a conversation message to short-term memory.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "user_id": {"type": "string"},
                        "role": {"type": "string", "enum": ["user", "assistant", "system"]},
                        "content": {"type": "string"},
                    },
                    "required": ["session_id", "role", "content"],
                },
                server_name="memory",
            ),
            ToolDefinition(
                name="memory_get_history",
                description="Get recent conversation history for a session.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                        "limit": {"type": "integer", "default": 20},
                    },
                    "required": ["session_id"],
                },
                server_name="memory",
            ),
            ToolDefinition(
                name="memory_summarize",
                description="Summarize and compress old conversation history.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string"},
                    },
                    "required": ["session_id"],
                },
                server_name="memory",
            ),
        ]

    async def call_tool(self, request: ToolCallRequest) -> ToolCallResponse:
        """Execute a memory tool."""
        if not self._memory:
            return ToolCallResponse(
                id=request.id,
                success=False,
                error="Memory service not initialized",
            )

        args = dict(request.arguments)
        args.pop("_context", None)
        tool_name = request.tool_name

        try:
            if tool_name == "memory_recall":
                ctx = await self._memory.recall(
                    query=args["query"],
                    guild_id=args.get("guild_id", 0),
                    session_id=args.get("session_id", ""),
                )
                return ToolCallResponse(
                    id=request.id,
                    success=True,
                    result={
                        "facts": [
                            {"content": f.content, "type": f.fact_type, "confidence": f.confidence}
                            for f in ctx.semantic_facts
                        ],
                        "recent_messages": [
                            {"role": m.role, "content": m.content}
                            for m in ctx.recent_messages
                        ],
                    },
                )

            elif tool_name == "memory_store":
                await self._memory.store_fact(
                    content=args["content"],
                    fact_type=args.get("fact_type", "fact"),
                    importance=args.get("importance", 0.5),
                    guild_id=args.get("guild_id", 0),
                )
                return ToolCallResponse(
                    id=request.id,
                    success=True,
                    result={"stored": True},
                )

            elif tool_name == "memory_add_message":
                await self._memory.add_message(
                    session_id=args["session_id"],
                    user_id=args.get("user_id", ""),
                    role=args["role"],
                    content=args["content"],
                )
                return ToolCallResponse(
                    id=request.id,
                    success=True,
                    result={"added": True},
                )

            elif tool_name == "memory_get_history":
                messages = await self._memory.get_history(
                    session_id=args["session_id"],
                    limit=args.get("limit", 20),
                )
                return ToolCallResponse(
                    id=request.id,
                    success=True,
                    result={
                        "messages": [
                            {"role": m.role, "content": m.content, "timestamp": str(m.timestamp)}
                            for m in messages
                        ]
                    },
                )

            elif tool_name == "memory_summarize":
                summary = await self._memory.summarize_session(
                    session_id=args["session_id"],
                )
                return ToolCallResponse(
                    id=request.id,
                    success=True,
                    result={"summary": summary},
                )

            else:
                return ToolCallResponse(
                    id=request.id,
                    success=False,
                    error=f"Unknown memory tool: {tool_name}",
                )

        except Exception as e:
            return ToolCallResponse(
                id=request.id,
                success=False,
                error=str(e),
            )
