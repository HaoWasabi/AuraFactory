# app/knowledge/store.py
"""
Server Knowledge Store — persist and query per-guild knowledge.
Phase 1: JSON file storage (simple, debug-friendly).
Phase 2: Swap to Bedrock Knowledge Base / DynamoDB.
"""
import json
import logging
from pathlib import Path
from typing import Optional

from app.knowledge.models import ServerKnowledge, ChannelInfo, RoleInfo, PinnedMessage, ScheduledEvent

logger = logging.getLogger(__name__)

# Default storage directory
DEFAULT_STORAGE_DIR = Path("data/knowledge")


class ServerKnowledgeStore:
    """
    Persists ServerKnowledge per guild.

    Phase 1: JSON files (one per guild).
    Phase 2: DynamoDB (structured) + Bedrock KB (vector/RAG).

    Interface is stable — only implementation changes in Phase 2.
    """

    def __init__(self, storage_dir: Optional[Path] = None):
        self._storage_dir = storage_dir or DEFAULT_STORAGE_DIR
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        # In-memory cache for fast access
        self._cache: dict[int, ServerKnowledge] = {}
        self._summary_cache: dict[int, str] = {}

    def _guild_path(self, guild_id: int) -> Path:
        """Path to a guild's knowledge JSON file."""
        return self._storage_dir / f"guild_{guild_id}.json"

    async def save(self, knowledge: ServerKnowledge) -> None:
        """Persist server knowledge to storage."""
        self._cache[knowledge.guild_id] = knowledge
        # Invalidate summary cache on save
        self._summary_cache.pop(knowledge.guild_id, None)

        data = self._serialize(knowledge)
        path = self._guild_path(knowledge.guild_id)

        try:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info(f"Saved knowledge for guild {knowledge.guild_id}")
        except Exception as e:
            logger.error(f"Failed to save knowledge for guild {knowledge.guild_id}: {e}")

    async def load(self, guild_id: int) -> Optional[ServerKnowledge]:
        """Load server knowledge from storage."""
        # Check cache first
        if guild_id in self._cache:
            return self._cache[guild_id]

        path = self._guild_path(guild_id)
        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            knowledge = self._deserialize(data)
            self._cache[guild_id] = knowledge
            return knowledge
        except Exception as e:
            logger.error(f"Failed to load knowledge for guild {guild_id}: {e}")
            return None

    async def exists(self, guild_id: int) -> bool:
        """Check if knowledge exists for a guild (= bot has been set up)."""
        if guild_id in self._cache:
            return True
        return self._guild_path(guild_id).exists()

    async def is_setup_complete(self, guild_id: int) -> bool:
        """Check if initial setup has been completed for this guild."""
        knowledge = await self.load(guild_id)
        if knowledge is None:
            return False
        return knowledge.setup_complete

    async def mark_setup_complete(self, guild_id: int) -> None:
        """Mark guild setup as complete."""
        knowledge = await self.load(guild_id)
        if knowledge:
            knowledge.setup_complete = True
            await self.save(knowledge)

    async def get_context_string(self, guild_id: int) -> str:
        """Get the knowledge as a context string for LLM prompts."""
        knowledge = await self.load(guild_id)
        if knowledge is None:
            return "No server knowledge available."
        return knowledge.to_context_string()

    async def get_summary_string(self, guild_id: int) -> str:
        """Get compact cached summary for LLM prompts (~200 tokens)."""
        # Return from cache if available
        if guild_id in self._summary_cache:
            return self._summary_cache[guild_id]

        knowledge = await self.load(guild_id)
        if knowledge is None:
            return "New server — no knowledge yet."

        summary = knowledge.to_summary_string()
        self._summary_cache[guild_id] = summary
        return summary

    async def query(self, guild_id: int, question: str) -> str:
        """
        Simple keyword-based query against server knowledge.
        Phase 1: string matching on context.
        Phase 2: vector search via Bedrock KB.
        """
        knowledge = await self.load(guild_id)
        if knowledge is None:
            return "I don't have information about this server yet."

        # Simple approach: return full context (LLM will filter)
        # Phase 2: embed question, search vector store, return top-k chunks
        return knowledge.to_context_string()

    async def delete(self, guild_id: int) -> None:
        """Remove knowledge for a guild (e.g., bot removed from server)."""
        self._cache.pop(guild_id, None)
        path = self._guild_path(guild_id)
        if path.exists():
            path.unlink()
            logger.info(f"Deleted knowledge for guild {guild_id}")

    # --- Serialization ---

    def _serialize(self, knowledge: ServerKnowledge) -> dict:
        """Convert ServerKnowledge to JSON-serializable dict."""
        return {
            "guild_id": knowledge.guild_id,
            "guild_name": knowledge.guild_name,
            "description": knowledge.description,
            "member_count": knowledge.member_count,
            "categories": knowledge.categories,
            "rules_text": knowledge.rules_text,
            "last_crawled": knowledge.last_crawled,
            "setup_complete": knowledge.setup_complete,
            "channels": [
                {
                    "id": ch.id, "name": ch.name, "type": ch.type,
                    "category": ch.category, "description": ch.description,
                    "position": ch.position,
                }
                for ch in knowledge.channels
            ],
            "roles": [
                {
                    "id": r.id, "name": r.name, "color": r.color,
                    "member_count": r.member_count, "is_admin": r.is_admin,
                    "position": r.position,
                }
                for r in knowledge.roles
            ],
            "pinned_messages": [
                {
                    "channel_name": p.channel_name, "content": p.content,
                    "author": p.author, "pinned_at": p.pinned_at,
                }
                for p in knowledge.pinned_messages
            ],
            "events": [
                {
                    "name": e.name, "description": e.description,
                    "start_time": e.start_time, "end_time": e.end_time,
                    "location": e.location,
                }
                for e in knowledge.events
            ],
        }

    def _deserialize(self, data: dict) -> ServerKnowledge:
        """Convert dict back to ServerKnowledge."""
        return ServerKnowledge(
            guild_id=data["guild_id"],
            guild_name=data["guild_name"],
            description=data.get("description", ""),
            member_count=data.get("member_count", 0),
            categories=data.get("categories", []),
            rules_text=data.get("rules_text", ""),
            last_crawled=data.get("last_crawled"),
            setup_complete=data.get("setup_complete", False),
            channels=[
                ChannelInfo(**ch) for ch in data.get("channels", [])
            ],
            roles=[
                RoleInfo(**r) for r in data.get("roles", [])
            ],
            pinned_messages=[
                PinnedMessage(**p) for p in data.get("pinned_messages", [])
            ],
            events=[
                ScheduledEvent(**e) for e in data.get("events", [])
            ],
        )
