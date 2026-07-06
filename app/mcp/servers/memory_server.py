"""
Memory MCP Server — Exposes memory operations as MCP tools.

Tools:
- memory.recall: Retrieve memories by key or semantic query.
- memory.store: Persist a new memory (key-value with metadata).
- memory.search: Semantic search across all stored memories.
- memory.forget: Delete a memory by key.
- memory.summarize: Generate a summary of memories matching a query.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.mcp.protocol import ToolDefinition
from app.mcp.server import MCPServer

logger = logging.getLogger(__name__)


class MemoryMCPServer(MCPServer):
    """MCP server for memory operations.

    Delegates all tool calls to a MemoryService instance.
    """

    def __init__(self, memory_service: Any = None) -> None:
        super().__init__()
        self._memory_service = memory_service
        self._register_tools()

    def set_memory_service(self, memory_service: Any) -> None:
        """Inject the memory service (can be set after construction)."""
        self._memory_service = memory_service

    def _get_service(self) -> Any:
        """Get memory service or raise if not configured."""
        if self._memory_service is None:
            raise RuntimeError(
                "MemoryService not configured. Call set_memory_service() first."
            )
        return self._memory_service

    # ------------------------------------------------------------------
    # Tool Registration
    # ------------------------------------------------------------------

    def _register_tools(self) -> None:
        """Register all memory tools."""

        # memory.recall
        self.register_tool(
            ToolDefinition(
                name="memory.recall",
                description=(
                    "Retrieve a stored memory by key or semantic query. "
                    "Returns the memory content and metadata if found."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Exact key to recall.",
                        },
                        "query": {
                            "type": "string",
                            "description": "Semantic query (used if key not provided).",
                        },
                        "namespace": {
                            "type": "string",
                            "description": "Memory namespace (default: 'default').",
                        },
                    },
                },
                risk_level="low",
            ),
            self._handle_recall,
        )

        # memory.store
        self.register_tool(
            ToolDefinition(
                name="memory.store",
                description=(
                    "Store a new memory with a key, value, and optional metadata. "
                    "Overwrites if key already exists."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Unique identifier for the memory.",
                        },
                        "value": {
                            "type": "string",
                            "description": "The content to store.",
                        },
                        "metadata": {
                            "type": "object",
                            "description": "Optional metadata dict.",
                        },
                        "namespace": {
                            "type": "string",
                            "description": "Memory namespace (default: 'default').",
                        },
                    },
                    "required": ["key", "value"],
                },
                risk_level="low",
            ),
            self._handle_store,
        )

        # memory.search
        self.register_tool(
            ToolDefinition(
                name="memory.search",
                description=(
                    "Semantic search across stored memories. "
                    "Returns top-k results ranked by relevance."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query.",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of results (default: 5).",
                        },
                        "namespace": {
                            "type": "string",
                            "description": "Memory namespace (default: 'default').",
                        },
                    },
                    "required": ["query"],
                },
                risk_level="low",
            ),
            self._handle_search,
        )

        # memory.forget
        self.register_tool(
            ToolDefinition(
                name="memory.forget",
                description="Delete a memory by its key. Irreversible.",
                parameters={
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Key of the memory to delete.",
                        },
                        "namespace": {
                            "type": "string",
                            "description": "Memory namespace (default: 'default').",
                        },
                    },
                    "required": ["key"],
                },
                risk_level="medium",
            ),
            self._handle_forget,
        )

        # memory.summarize
        self.register_tool(
            ToolDefinition(
                name="memory.summarize",
                description=(
                    "Generate a summary of memories matching a query. "
                    "Useful for condensing context before passing to an agent."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Query to filter memories for summarization.",
                        },
                        "max_memories": {
                            "type": "integer",
                            "description": "Max memories to include (default: 10).",
                        },
                        "namespace": {
                            "type": "string",
                            "description": "Memory namespace (default: 'default').",
                        },
                    },
                    "required": ["query"],
                },
                risk_level="low",
            ),
            self._handle_summarize,
        )

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_recall(
        self,
        key: Optional[str] = None,
        query: Optional[str] = None,
        namespace: str = "default",
    ) -> dict:
        service = self._get_service()
        if key:
            result = await service.recall(key=key, namespace=namespace)
        elif query:
            result = await service.recall(query=query, namespace=namespace)
        else:
            raise ValueError("Either 'key' or 'query' must be provided")
        return {"memory": result}

    async def _handle_store(
        self,
        key: str,
        value: str,
        metadata: Optional[dict] = None,
        namespace: str = "default",
    ) -> dict:
        service = self._get_service()
        await service.store(
            key=key, value=value, metadata=metadata or {}, namespace=namespace
        )
        return {"stored": True, "key": key, "namespace": namespace}

    async def _handle_search(
        self,
        query: str,
        top_k: int = 5,
        namespace: str = "default",
    ) -> dict:
        service = self._get_service()
        results = await service.search(query=query, top_k=top_k, namespace=namespace)
        return {"results": results, "count": len(results)}

    async def _handle_forget(
        self,
        key: str,
        namespace: str = "default",
    ) -> dict:
        service = self._get_service()
        await service.forget(key=key, namespace=namespace)
        return {"deleted": True, "key": key, "namespace": namespace}

    async def _handle_summarize(
        self,
        query: str,
        max_memories: int = 10,
        namespace: str = "default",
    ) -> dict:
        service = self._get_service()
        summary = await service.summarize(
            query=query, max_memories=max_memories, namespace=namespace
        )
        return {"summary": summary}

    # ------------------------------------------------------------------
    # MCPServer interface
    # ------------------------------------------------------------------

    def get_server_name(self) -> str:
        return "memory"
