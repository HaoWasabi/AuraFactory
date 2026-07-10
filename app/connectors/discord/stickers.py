"""Discord Stickers Connector — kwargs pattern. Actions: create, delete, list"""
from __future__ import annotations

import io
import logging
from typing import Any, Dict, List

import aiohttp
import nextcord

from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class StickersConnector(BaseConnector):
    """Connector for managing Discord guild stickers."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Router
    # ------------------------------------------------------------------

    async def execute(self, action: str, guild: nextcord.Guild, **kwargs) -> Any:
        """Dispatch to the appropriate action handler.

        Args:
            action: One of ``"create"``, ``"delete"``, ``"list"``.
            guild:  The target :class:`nextcord.Guild`.
            **kwargs: Action-specific parameters (see individual methods).

        Returns:
            Action-specific dict or list (see individual methods).

        Raises:
            ValueError: Unknown action name.
        """
        actions: Dict[str, Any] = {
            "create": self.create,
            "delete": self.delete,
            "list":   self.list,
        }

        handler = actions.get(action)
        if handler is None:
            raise ValueError(
                f"Unknown sticker action '{action}'. "
                f"Valid actions: {list(actions.keys())}"
            )

        return await handler(guild=guild, **kwargs)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def create(
        self,
        guild: nextcord.Guild,
        name: str,
        file_url: str,
        tags: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Download a PNG/APNG from *file_url* and upload it as a guild sticker.

        Args:
            guild:       Target guild.
            name:        Sticker name (2–30 chars, Discord limit).
            file_url:    Public URL of the sticker image (PNG / APNG / Lottie).
            tags:        Related emoji string used as the sticker's ``emoji`` tag.
            **kwargs:
                description (str): Optional sticker description (max 100 chars).

        Returns:
            ``{"id": str, "name": str, "tags": str}``

        Raises:
            ValueError:      *name* or *tags* is empty / missing.
            RuntimeError:    Failed to download the file or Discord API error.
            PermissionError: Bot lacks ``MANAGE_GUILD_EXPRESSIONS`` permission.
        """
        if not name or not name.strip():
            raise ValueError("Sticker 'name' must be a non-empty string.")
        if not tags or not tags.strip():
            raise ValueError("Sticker 'tags' (emoji) must be a non-empty string.")
        if not file_url or not file_url.strip():
            raise ValueError("'file_url' must be a non-empty URL string.")

        description: str = kwargs.get("description", "")

        # Download sticker image
        logger.debug("Downloading sticker image from %s", file_url)
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(file_url) as response:
                    if response.status != 200:
                        raise RuntimeError(
                            f"Failed to download sticker image: "
                            f"HTTP {response.status} from {file_url}"
                        )
                    data: bytes = await response.read()
        except aiohttp.ClientError as exc:
            raise RuntimeError(
                f"Network error while downloading sticker image: {exc}"
            ) from exc

        # Build nextcord.File from raw bytes
        fp = io.BytesIO(data)
        sticker_file = nextcord.File(fp=fp, filename="sticker.png")

        # Upload to Discord
        logger.info("Creating sticker '%s' in guild '%s' (%s)", name, guild.name, guild.id)
        try:
            sticker: nextcord.GuildSticker = await guild.create_sticker(
                name=name,
                file=sticker_file,
                emoji=tags,
                description=description,
            )
        except nextcord.Forbidden as exc:
            raise PermissionError(
                f"Bot lacks permission to create stickers in guild '{guild.name}': {exc}"
            ) from exc
        except nextcord.HTTPException as exc:
            raise RuntimeError(
                f"Discord API error while creating sticker: {exc}"
            ) from exc

        logger.info("Sticker created — id=%s name=%s", sticker.id, sticker.name)
        return {
            "id":   str(sticker.id),
            "name": sticker.name,
            "tags": sticker.emoji,
        }

    # ------------------------------------------------------------------

    async def delete(
        self,
        guild: nextcord.Guild,
        sticker_id: int | str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Delete a guild sticker by ID.

        Args:
            guild:      Target guild.
            sticker_id: Integer (or string) ID of the sticker to delete.
            **kwargs:   Unused; accepted for interface uniformity.

        Returns:
            ``{"deleted": True, "id": str}``

        Raises:
            ValueError:      *sticker_id* is invalid or sticker not found in the guild.
            PermissionError: Bot lacks ``MANAGE_GUILD_EXPRESSIONS`` permission.
            RuntimeError:    Discord API error.
        """
        try:
            sticker_id_int = int(sticker_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"'sticker_id' must be a valid integer, got {sticker_id!r}"
            ) from exc

        # Locate sticker in the cached list
        await guild.fetch_stickers()          # refresh cache
        sticker: nextcord.GuildSticker | None = nextcord.utils.get(
            guild.stickers, id=sticker_id_int
        )
        if sticker is None:
            raise ValueError(
                f"No sticker with id={sticker_id_int} found in guild '{guild.name}'."
            )

        logger.info(
            "Deleting sticker id=%s name='%s' from guild '%s' (%s)",
            sticker.id, sticker.name, guild.name, guild.id,
        )
        try:
            await sticker.delete()
        except nextcord.Forbidden as exc:
            raise PermissionError(
                f"Bot lacks permission to delete stickers in guild '{guild.name}': {exc}"
            ) from exc
        except nextcord.HTTPException as exc:
            raise RuntimeError(
                f"Discord API error while deleting sticker id={sticker_id_int}: {exc}"
            ) from exc

        logger.info("Sticker id=%s deleted successfully.", sticker_id_int)
        return {"deleted": True, "id": str(sticker_id_int)}

    # ------------------------------------------------------------------

    async def list(
        self,
        guild: nextcord.Guild,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """Return all stickers currently in the guild.

        Args:
            guild:    Target guild.
            **kwargs: Unused; accepted for interface uniformity.

        Returns:
            List of ``{"id": str, "name": str, "tags": str, "url": str}``

        Raises:
            PermissionError: Bot lacks permission to view stickers.
            RuntimeError:    Discord API error.
        """
        logger.debug("Fetching stickers for guild '%s' (%s)", guild.name, guild.id)
        try:
            stickers: List[nextcord.GuildSticker] = await guild.fetch_stickers()
        except nextcord.Forbidden as exc:
            raise PermissionError(
                f"Bot lacks permission to list stickers in guild '{guild.name}': {exc}"
            ) from exc
        except nextcord.HTTPException as exc:
            raise RuntimeError(
                f"Discord API error while listing stickers: {exc}"
            ) from exc

        result = [
            {
                "id":   str(s.id),
                "name": s.name,
                "tags": s.emoji,
                "url":  s.url,
            }
            for s in stickers
        ]
        logger.info("Found %d sticker(s) in guild '%s'.", len(result), guild.name)
        return result
