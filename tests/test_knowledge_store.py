"""Tests for SQLite + FTS5 Knowledge Store."""

import pytest
import tempfile
import os
from pathlib import Path

from app.data.knowledge_store import KnowledgeStore


@pytest.fixture
async def store():
    """Create a temporary knowledge store for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ks = KnowledgeStore(data_dir=tmpdir)
        yield ks
        await ks.close()


class TestKnowledgeStore:
    """Test knowledge CRUD and FTS5 search."""

    @pytest.mark.asyncio
    async def test_ingest_and_search(self, store):
        guild_id = 12345
        await store.ingest_knowledge(
            guild_id=guild_id,
            category="rule",
            source="admin_input",
            content="No spamming in general chat. Keep it clean.",
            title="Rule #1",
            priority=10,
        )
        await store.ingest_knowledge(
            guild_id=guild_id,
            category="faq",
            source="admin_input",
            content="Voice channels are open 24/7 for gaming sessions.",
            title="Voice FAQ",
            priority=3,
        )

        results = await store.search_knowledge(guild_id, "spam")
        assert len(results) >= 1
        assert "spam" in results[0]["content"].lower()

    @pytest.mark.asyncio
    async def test_dedup_by_source_id(self, store):
        guild_id = 12345
        await store.ingest_knowledge(
            guild_id=guild_id, category="pin", source="pinned_message",
            source_id="msg_001", content="Original content", title="Pin"
        )
        await store.ingest_knowledge(
            guild_id=guild_id, category="pin", source="pinned_message",
            source_id="msg_001", content="Updated content", title="Pin v2"
        )
        results = await store.search_knowledge(guild_id, "content")
        # Should only have 1 result (upserted)
        pin_results = [r for r in results if r.get("source") == "pinned_message"]
        assert len(pin_results) <= 1

    @pytest.mark.asyncio
    async def test_conversation_persistence(self, store):
        guild_id = 12345
        await store.append_conversation(guild_id, "sess1", 456, "user", "Create a gaming channel")
        await store.append_conversation(guild_id, "sess1", 456, "assistant", "Done! Created #gaming")

        recent = await store.get_recent_conversations(guild_id, "sess1")
        assert len(recent) == 2
        assert recent[0]["role"] == "user"
        assert recent[1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_conversation_search(self, store):
        guild_id = 12345
        await store.append_conversation(guild_id, "sess1", 456, "user", "Setup a Minecraft server category")
        results = await store.search_conversations(guild_id, "Minecraft")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_preferences(self, store):
        guild_id = 12345
        await store.set_preference(guild_id, 456, "language", "vi")
        val = await store.get_preference(guild_id, 456, "language")
        assert val == "vi"

        # Overwrite
        await store.set_preference(guild_id, 456, "language", "en")
        val = await store.get_preference(guild_id, 456, "language")
        assert val == "en"

    @pytest.mark.asyncio
    async def test_guild_isolation(self, store):
        await store.ingest_knowledge(guild_id=111, category="rule", source="test", content="Guild A rule")
        await store.ingest_knowledge(guild_id=222, category="rule", source="test", content="Guild B rule")

        results_a = await store.search_knowledge(111, "rule")
        results_b = await store.search_knowledge(222, "rule")

        # Each guild should only see its own data
        for r in results_a:
            assert "Guild A" in r["content"]
        for r in results_b:
            assert "Guild B" in r["content"]

    @pytest.mark.asyncio
    async def test_delete_guild_data(self, store):
        guild_id = 99999
        await store.ingest_knowledge(guild_id=guild_id, category="test", source="test", content="temp data")
        await store.delete_guild_data(guild_id)
        # DB file should be gone
        db_path = store._data_dir / f"{guild_id}.db"
        assert not db_path.exists()
