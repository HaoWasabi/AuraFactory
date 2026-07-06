"""AuraFactory Knowledge System — Layer 6.

Provides guild knowledge storage, crawling, and retrieval.
"""
import logging
from typing import Any

from app.knowledge.crawler import GuildCrawler
from app.knowledge.store import ServerKnowledgeStore

logger = logging.getLogger(__name__)


class ServerCrawler:
    """Combined crawler + store wrapper used by main.py and discord_adapter.

    Provides crawl_and_store(guild) that the discord adapter calls.
    Initializes the actual GuildCrawler lazily when the bot becomes available.
    """

    def __init__(self, knowledge_store: Any = None, bot: Any = None) -> None:
        self._knowledge_store = knowledge_store
        self._bot = bot
        self._crawler: GuildCrawler | None = None

    def set_bot(self, bot: Any) -> None:
        """Set bot reference (called when bot is ready)."""
        self._bot = bot
        self._crawler = GuildCrawler(bot=bot)

    async def crawl_and_store(self, guild: Any) -> None:
        """Crawl a guild and store the knowledge snapshot.

        Args:
            guild: Nextcord Guild object.
        """
        # Lazy-init crawler with guild's bot reference
        if self._crawler is None:
            if self._bot is not None:
                self._crawler = GuildCrawler(bot=self._bot)
            else:
                # Use guild's client as bot fallback
                bot = getattr(guild, "_state", None)
                if bot is None:
                    bot = getattr(guild, "client", None)
                if bot is not None:
                    self._crawler = GuildCrawler(bot=bot)
                else:
                    logger.warning("Cannot crawl: no bot reference available")
                    return

        try:
            knowledge = await self._crawler.crawl(guild)
        except Exception as e:
            logger.error(f"Crawl failed for guild {guild.id}: {e}")
            return

        # Store if knowledge_store is available
        if self._knowledge_store is not None:
            try:
                snapshot = knowledge.__dict__ if hasattr(knowledge, '__dict__') else {}
                if hasattr(knowledge, 'to_dict'):
                    snapshot = knowledge.to_dict()
                await self._knowledge_store.save_snapshot(guild.id, snapshot)
                logger.info(f"Knowledge stored for guild {guild.name} ({guild.id})")
            except Exception as e:
                logger.warning(f"Failed to store knowledge for guild {guild.id}: {e}")
        else:
            logger.debug("No knowledge_store configured — crawl result discarded")


__all__: list[str] = ["ServerKnowledgeStore", "GuildCrawler", "ServerCrawler"]
