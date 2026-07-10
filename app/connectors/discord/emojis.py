"""Discord Emojis Connector — kwargs pattern. Actions: create, rename, delete, list"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import aiohttp
import nextcord

from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

# Discord emoji name constraints
_EMOJI_NAME_MIN = 2
_EMOJI_NAME_MAX = 32

# Boost-level emoji slot limits (regular + animated each)
# Tier 0: 50, Tier 1: 100, Tier 2: 150, Tier 3: 250
_EMOJI_LIMIT_BY_TIER: Dict[int, int] = {0: 50, 1: 100, 2: 150, 3: 250}

# aiohttp download timeout (seconds)
_DOWNLOAD_TIMEOUT = 15

# Maximum image size Discord accepts for emoji upload (256 KB)
_MAX_IMAGE_BYTES = 256 * 1024


def _emoji_limit(guild: nextcord.Guild) -> int:
    """Return the emoji slot limit for the guild based on its premium tier."""
    return _EMOJI_LIMIT_BY_TIER.get(guild.premium_tier, 50)


def _validate_emoji_name(name: str) -> None:
    """Raise ValueError if *name* is not a valid Discord emoji name."""
    if not name or not name.strip():
        raise ValueError("Emoji name cannot be empty")
    stripped = name.strip()
    if len(stripped) < _EMOJI_NAME_MIN:
        raise ValueError(
            f"Emoji name must be at least {_EMOJI_NAME_MIN} characters (got {len(stripped)})"
        )
    if len(stripped) > _EMOJI_NAME_MAX:
        raise ValueError(
            f"Emoji name must be at most {_EMOJI_NAME_MAX} characters (got {len(stripped)})"
        )
    # Discord only allows alphanumerics and underscores
    if not all(c.isalnum() or c == "_" for c in stripped):
        raise ValueError(
            f"Emoji name '{stripped}' contains invalid characters "
            "(only alphanumerics and underscores are allowed)"
        )


def _emoji_url(emoji: nextcord.Emoji) -> str:
    """Return the CDN URL for a custom emoji."""
    return str(emoji.url)


def _emoji_to_dict(emoji: nextcord.Emoji) -> Dict[str, Any]:
    """Serialize a nextcord.Emoji to a JSON-safe dict."""
    return {
        "id": str(emoji.id),
        "name": emoji.name,
        "url": _emoji_url(emoji),
        "animated": emoji.animated,
    }


class EmojisConnector(BaseConnector):
    """Emoji management — create, rename, delete, list custom guild emojis."""

    def __init__(self, bot: nextcord.Bot) -> None:
        self._bot = bot

    # ------------------------------------------------------------------
    # Dispatcher
    # ------------------------------------------------------------------

    async def execute(
        self, action: str, guild: nextcord.Guild, **kwargs
    ) -> Dict[str, Any]:
        actions = {
            "create": self.create,
            "rename": self.rename,
            "delete": self.delete,
            "list": self.list,
        }
        handler = actions.get(action)
        if handler is None:
            raise ValueError(
                f"Unknown action '{action}'. Available: {list(actions.keys())}"
            )
        return await handler(guild, **kwargs)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def create(
        self,
        guild: nextcord.Guild,
        name: str,
        image_url: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Download *image_url* and create a custom emoji named *name*.

        kwargs:
            roles (List[int | str]): Role IDs that may use the emoji.
                                     Empty / omitted = unrestricted.
            reason (str): Audit-log reason.

        Returns:
            {"id": str, "name": str, "url": str}

        Raises:
            ValueError: Invalid name or image URL, or guild is at emoji limit.
            PermissionError: Bot lacks manage_emojis_and_stickers.
            RuntimeError: Discord API failure.
        """
        # --- Validate name ---
        _validate_emoji_name(name)
        name = name.strip()

        # --- Validate URL ---
        if not image_url or not image_url.startswith(("http://", "https://")):
            raise ValueError(
                f"image_url must be a valid HTTP(S) URL (got '{image_url}')"
            )

        # --- Check emoji slot headroom ---
        current_count = len([e for e in guild.emojis if not e.animated])
        animated_count = len([e for e in guild.emojis if e.animated])
        limit = _emoji_limit(guild)

        # We don't know the type of the incoming image until we download it,
        # so we check the more-constrained static slot conservatively.
        # Discord tracks animated / static separately but both share the same
        # per-tier cap, so we flag only when *both* pools are full.
        if current_count >= limit and animated_count >= limit:
            raise ValueError(
                f"Guild has reached the emoji limit for boost tier "
                f"{guild.premium_tier} ({limit} static + {limit} animated). "
                "Delete existing emojis or boost the server first."
            )

        # --- Resolve optional roles ---
        role_ids: List[Any] = kwargs.pop("roles", []) or []
        roles: List[nextcord.Role] = []
        for r_id in role_ids:
            role = guild.get_role(int(r_id))
            if role is None:
                raise ValueError(f"Role '{r_id}' not found in guild")
            roles.append(role)

        reason: str = kwargs.pop("reason", "Created by AI Agent")

        # --- Download image ---
        timeout = aiohttp.ClientTimeout(total=_DOWNLOAD_TIMEOUT)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(image_url) as response:
                    if response.status != 200:
                        raise RuntimeError(
                            f"Failed to download emoji image: HTTP {response.status} "
                            f"from '{image_url}'"
                        )
                    image_bytes = await response.read()
        except aiohttp.InvalidURL:
            raise ValueError(f"image_url is not a valid URL: '{image_url}'")
        except aiohttp.ClientConnectorError as exc:
            raise RuntimeError(f"Could not connect to image URL '{image_url}': {exc}")
        except aiohttp.ClientError as exc:
            raise RuntimeError(f"Failed to download emoji image: {exc}")

        if not image_bytes:
            raise ValueError("Downloaded image is empty")

        if len(image_bytes) > _MAX_IMAGE_BYTES:
            raise ValueError(
                f"Image is too large ({len(image_bytes) / 1024:.1f} KB). "
                f"Discord requires emoji images ≤ 256 KB."
            )

        # --- Create emoji ---
        try:
            emoji = await guild.create_custom_emoji(
                name=name,
                image=image_bytes,
                roles=roles if roles else [],
                reason=reason,
            )
            logger.info(
                "Created emoji '%s' (id=%s) in guild '%s'",
                emoji.name,
                emoji.id,
                guild.name,
            )
            return {"id": str(emoji.id), "name": emoji.name, "url": _emoji_url(emoji)}
        except nextcord.Forbidden:
            raise PermissionError("manage_emojis_and_stickers")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to create emoji: {exc}")

    # ------------------------------------------------------------------

    async def rename(
        self,
        guild: nextcord.Guild,
        emoji_id: int,
        new_name: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Rename an existing custom emoji.

        kwargs:
            reason (str): Audit-log reason.

        Returns:
            {"id": str, "name": str}

        Raises:
            ValueError: Invalid new_name or emoji not found.
            PermissionError: Bot lacks manage_emojis_and_stickers.
            RuntimeError: Discord API failure.
        """
        _validate_emoji_name(new_name)
        new_name = new_name.strip()

        reason: str = kwargs.pop("reason", "Renamed by AI Agent")

        # Fetch from guild cache first, fall back to API fetch
        try:
            emoji = await guild.fetch_emoji(int(emoji_id))
        except nextcord.NotFound:
            raise ValueError(f"Emoji '{emoji_id}' not found in guild '{guild.name}'")
        except nextcord.Forbidden:
            raise PermissionError("manage_emojis_and_stickers")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to fetch emoji '{emoji_id}': {exc}")

        try:
            await emoji.edit(name=new_name, reason=reason)
            # Re-fetch to get the updated object from the API
            emoji = await guild.fetch_emoji(int(emoji_id))
            logger.info(
                "Renamed emoji id=%s to '%s' in guild '%s'",
                emoji_id,
                emoji.name,
                guild.name,
            )
            return {"id": str(emoji.id), "name": emoji.name}
        except nextcord.Forbidden:
            raise PermissionError("manage_emojis_and_stickers")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to rename emoji '{emoji_id}': {exc}")

    # ------------------------------------------------------------------

    async def delete(
        self,
        guild: nextcord.Guild,
        emoji_id: int,
        **kwargs,
    ) -> Dict[str, Any]:
        """Delete a custom emoji from the guild.

        kwargs:
            reason (str): Audit-log reason.

        Returns:
            {"deleted": True, "id": str}

        Raises:
            ValueError: Emoji not found.
            PermissionError: Bot lacks manage_emojis_and_stickers.
            RuntimeError: Discord API failure.
        """
        reason: str = kwargs.pop("reason", "Deleted by AI Agent")

        try:
            emoji = await guild.fetch_emoji(int(emoji_id))
        except nextcord.NotFound:
            raise ValueError(f"Emoji '{emoji_id}' not found in guild '{guild.name}'")
        except nextcord.Forbidden:
            raise PermissionError("manage_emojis_and_stickers")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to fetch emoji '{emoji_id}': {exc}")

        try:
            await emoji.delete(reason=reason)
            logger.info(
                "Deleted emoji '%s' (id=%s) from guild '%s'",
                emoji.name,
                emoji_id,
                guild.name,
            )
            return {"deleted": True, "id": str(emoji_id)}
        except nextcord.Forbidden:
            raise PermissionError("manage_emojis_and_stickers")
        except nextcord.HTTPException as exc:
            raise RuntimeError(f"Failed to delete emoji '{emoji_id}': {exc}")

    # ------------------------------------------------------------------

    async def list(
        self,
        guild: nextcord.Guild,
        **kwargs,
    ) -> Dict[str, Any]:
        """Return all custom emojis in the guild.

        kwargs:
            animated_only (bool): If True, return only animated emojis.
            static_only (bool):   If True, return only static emojis.

        Returns:
            {
                "emojis": [{"id", "name", "url", "animated"}, ...],
                "count": int,
                "static_count": int,
                "animated_count": int,
                "limit": int,
                "boost_tier": int,
            }
        """
        animated_only: bool = kwargs.pop("animated_only", False)
        static_only: bool = kwargs.pop("static_only", False)

        if animated_only and static_only:
            raise ValueError(
                "animated_only and static_only cannot both be True — "
                "that would return an empty list."
            )

        all_emojis = guild.emojis  # cached list from gateway events

        if animated_only:
            filtered = [e for e in all_emojis if e.animated]
        elif static_only:
            filtered = [e for e in all_emojis if not e.animated]
        else:
            filtered = list(all_emojis)

        static_count = sum(1 for e in all_emojis if not e.animated)
        animated_count = sum(1 for e in all_emojis if e.animated)
        limit = _emoji_limit(guild)

        logger.debug(
            "Listed %d/%d emojis for guild '%s' (tier %d, limit %d)",
            len(filtered),
            len(all_emojis),
            guild.name,
            guild.premium_tier,
            limit,
        )

        return {
            "emojis": [_emoji_to_dict(e) for e in filtered],
            "count": len(filtered),
            "static_count": static_count,
            "animated_count": animated_count,
            "limit": limit,
            "boost_tier": guild.premium_tier,
        }
