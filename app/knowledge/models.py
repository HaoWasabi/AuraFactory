"""Knowledge models — data structures for guild knowledge."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ChannelInfo:
    """Minimal channel representation."""

    id: int
    name: str
    type: str
    category_id: int | None = None
    topic: str | None = None
    position: int = 0


@dataclass
class RoleInfo:
    """Minimal role representation."""

    id: int
    name: str
    color: int = 0
    position: int = 0
    permissions: int = 0
    mentionable: bool = False
    managed: bool = False


@dataclass
class CategoryInfo:
    """Minimal category representation."""

    id: int
    name: str
    position: int = 0
    channel_ids: list[int] = field(default_factory=list)


@dataclass
class GuildKnowledge:
    """Complete knowledge snapshot of a guild.

    Attributes:
        guild_id: Discord guild identifier.
        guild_name: Human-readable guild name.
        channels: List of channel info dicts.
        roles: List of role info dicts.
        categories: List of category info dicts.
        member_count: Total guild member count.
        rules: List of guild rule strings.
        crawled_at: Timestamp of crawl.
    """

    guild_id: int
    guild_name: str
    channels: list[dict] = field(default_factory=list)
    roles: list[dict] = field(default_factory=list)
    categories: list[dict] = field(default_factory=list)
    member_count: int = 0
    rules: list[str] = field(default_factory=list)
    crawled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """Serialize to dict for JSON storage."""
        return {
            "guild_id": self.guild_id,
            "guild_name": self.guild_name,
            "channels": self.channels,
            "roles": self.roles,
            "categories": self.categories,
            "member_count": self.member_count,
            "rules": self.rules,
            "crawled_at": self.crawled_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> GuildKnowledge:
        """Deserialize from dict."""
        crawled_at = data.get("crawled_at")
        if isinstance(crawled_at, str):
            crawled_at = datetime.fromisoformat(crawled_at)
        elif crawled_at is None:
            crawled_at = datetime.now(timezone.utc)

        return cls(
            guild_id=data["guild_id"],
            guild_name=data.get("guild_name", ""),
            channels=data.get("channels", []),
            roles=data.get("roles", []),
            categories=data.get("categories", []),
            member_count=data.get("member_count", 0),
            rules=data.get("rules", []),
            crawled_at=crawled_at,
        )
