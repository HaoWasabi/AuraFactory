"""Discord Soundboard Connector — kwargs pattern. Actions: create, delete, list"""
from __future__ import annotations

import base64
import logging
from typing import Any, Dict, List

import aiohttp
import nextcord

from app.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Discord REST route helpers
# ---------------------------------------------------------------------------
# nextcord's HTTP client exposes `bot.http.request(route, ...)`.
# We build Route objects for the three Soundboard endpoints.
# ---------------------------------------------------------------------------

_SOUNDBOARD_LIST   = "/guilds/{guild_id}/soundboard-sounds"
_SOUNDBOARD_CREATE = "/guilds/{guild_id}/soundboard-sounds"
_SOUNDBOARD_DELETE = "/guilds/{guild_id}/soundboard-sounds/{sound_id}"


class SoundboardConnector(BaseConnector):
    """Connector for managing Discord guild soundboard sounds.

    nextcord does not yet expose native soundboard methods, so every action
    is implemented via low-level REST calls through ``bot.http.request``.
    """

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
                f"Unknown soundboard action '{action}'. "
                f"Valid actions: {list(actions.keys())}"
            )

        return await handler(guild=guild, **kwargs)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _download_sound(self, file_url: str) -> bytes:
        """Download audio bytes from *file_url* with a 15-second timeout.

        Args:
            file_url: Publicly accessible URL of the audio file.

        Returns:
            Raw audio bytes.

        Raises:
            RuntimeError: HTTP error or network failure.
        """
        logger.debug("Downloading soundboard audio from %s", file_url)
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(file_url) as response:
                    if response.status != 200:
                        raise RuntimeError(
                            f"Failed to download sound file: "
                            f"HTTP {response.status} from {file_url}"
                        )
                    return await response.read()
        except aiohttp.ClientError as exc:
            raise RuntimeError(
                f"Network error while downloading sound file: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def create(
        self,
        guild: nextcord.Guild,
        name: str,
        file_url: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Download an audio file and upload it as a guild soundboard sound.

        Discord expects the sound as a base64-encoded Data URI in the JSON body.
        Supported formats: MP3, OGG (Vorbis), or FLAC (≤ 512 KB, ≤ 5.2 s).

        Args:
            guild:    Target guild.
            name:     Sound name (2–32 chars).
            file_url: Public URL of the audio file.
            **kwargs:
                volume     (float, 0.0–1.0): Playback volume. Defaults to ``1.0``.
                emoji_name (str):            Unicode emoji associated with the sound.

        Returns:
            ``{"id": str, "name": str}``

        Raises:
            ValueError:      *name* or *file_url* is empty / invalid.
            PermissionError: Bot lacks ``CREATE_GUILD_EXPRESSIONS`` permission.
            RuntimeError:    Download failure or Discord API error.
        """
        if not name or not name.strip():
            raise ValueError("Sound 'name' must be a non-empty string.")
        if not file_url or not file_url.strip():
            raise ValueError("'file_url' must be a non-empty URL string.")

        volume: float     = float(kwargs.get("volume", 1.0))
        emoji_name: str   = kwargs.get("emoji_name", "")

        if not (0.0 <= volume <= 1.0):
            raise ValueError(f"'volume' must be between 0.0 and 1.0, got {volume}.")

        # Download and base64-encode the audio
        audio_bytes = await self._download_sound(file_url)
        # Guess content type from URL extension; default to ogg
        url_lower = file_url.lower()
        if url_lower.endswith(".mp3"):
            mime = "audio/mpeg"
        elif url_lower.endswith(".flac"):
            mime = "audio/flac"
        else:
            mime = "audio/ogg"

        sound_b64   = base64.b64encode(audio_bytes).decode("utf-8")
        sound_data  = f"data:{mime};base64,{sound_b64}"

        payload: Dict[str, Any] = {
            "name":   name,
            "sound":  sound_data,
            "volume": volume,
        }
        if emoji_name:
            payload["emoji_name"] = emoji_name

        route = nextcord.http.Route(
            "POST",
            _SOUNDBOARD_CREATE,
            guild_id=guild.id,
        )

        logger.info(
            "Creating soundboard sound '%s' in guild '%s' (%s)",
            name, guild.name, guild.id,
        )
        try:
            response_data: Dict[str, Any] = await self._bot.http.request(
                route, json=payload
            )
        except nextcord.Forbidden as exc:
            raise PermissionError(
                f"Bot lacks permission to create soundboard sounds in "
                f"guild '{guild.name}': {exc}"
            ) from exc
        except nextcord.HTTPException as exc:
            raise RuntimeError(
                f"Discord API error while creating soundboard sound: {exc}"
            ) from exc

        sound_id = str(response_data.get("sound_id", response_data.get("id", "")))
        logger.info("Soundboard sound created — id=%s name=%s", sound_id, name)
        return {
            "id":   sound_id,
            "name": response_data.get("name", name),
        }

    # ------------------------------------------------------------------

    async def delete(
        self,
        guild: nextcord.Guild,
        sound_id: int | str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Delete a guild soundboard sound by ID.

        Args:
            guild:    Target guild.
            sound_id: Integer (or string) ID of the sound to delete.
            **kwargs: Unused; accepted for interface uniformity.

        Returns:
            ``{"deleted": True}``

        Raises:
            ValueError:      *sound_id* is not a valid integer.
            PermissionError: Bot lacks ``MANAGE_GUILD_EXPRESSIONS`` permission.
            RuntimeError:    Discord API error.
        """
        try:
            sound_id_int = int(sound_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"'sound_id' must be a valid integer, got {sound_id!r}"
            ) from exc

        route = nextcord.http.Route(
            "DELETE",
            _SOUNDBOARD_DELETE,
            guild_id=guild.id,
            sound_id=sound_id_int,
        )

        logger.info(
            "Deleting soundboard sound id=%s from guild '%s' (%s)",
            sound_id_int, guild.name, guild.id,
        )
        try:
            await self._bot.http.request(route)
        except nextcord.Forbidden as exc:
            raise PermissionError(
                f"Bot lacks permission to delete soundboard sounds in "
                f"guild '{guild.name}': {exc}"
            ) from exc
        except nextcord.HTTPException as exc:
            raise RuntimeError(
                f"Discord API error while deleting soundboard sound "
                f"id={sound_id_int}: {exc}"
            ) from exc

        logger.info("Soundboard sound id=%s deleted successfully.", sound_id_int)
        return {"deleted": True}

    # ------------------------------------------------------------------

    async def list(
        self,
        guild: nextcord.Guild,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """Return all soundboard sounds currently in the guild.

        Args:
            guild:    Target guild.
            **kwargs: Unused; accepted for interface uniformity.

        Returns:
            List of ``{"id": str, "name": str, "volume": float}``

        Raises:
            PermissionError: Bot lacks permission to view soundboard sounds.
            RuntimeError:    Discord API error.
        """
        route = nextcord.http.Route(
            "GET",
            _SOUNDBOARD_LIST,
            guild_id=guild.id,
        )

        logger.debug(
            "Fetching soundboard sounds for guild '%s' (%s)", guild.name, guild.id
        )
        try:
            data: Dict[str, Any] = await self._bot.http.request(route)
        except nextcord.Forbidden as exc:
            raise PermissionError(
                f"Bot lacks permission to list soundboard sounds in "
                f"guild '{guild.name}': {exc}"
            ) from exc
        except nextcord.HTTPException as exc:
            raise RuntimeError(
                f"Discord API error while listing soundboard sounds: {exc}"
            ) from exc

        # Discord returns {"items": [...]} for guild soundboard list
        raw_items: List[Dict[str, Any]] = data.get("items", data) if isinstance(data, dict) else data

        result = [
            {
                "id":     str(item.get("sound_id", item.get("id", ""))),
                "name":   item.get("name", ""),
                "volume": float(item.get("volume", 1.0)),
            }
            for item in raw_items
        ]
        logger.info(
            "Found %d soundboard sound(s) in guild '%s'.", len(result), guild.name
        )
        return result
