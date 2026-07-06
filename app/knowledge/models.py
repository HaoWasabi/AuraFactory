# app/knowledge/models.py
"""
Data models for Server Knowledge Store.
Represents crawled server structure per guild.
"""
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime


@dataclass
class ChannelInfo:
    """A Discord channel's metadata."""
    id: int
    name: str
    type: str  # "text", "voice", "forum", "stage"
    category: Optional[str] = None
    description: Optional[str] = None
    position: int = 0


@dataclass
class RoleInfo:
    """A Discord role's metadata."""
    id: int
    name: str
    color: str = ""
    member_count: int = 0
    is_admin: bool = False
    position: int = 0


@dataclass
class PinnedMessage:
    """A pinned message snapshot."""
    channel_name: str
    content: str
    author: str
    pinned_at: Optional[str] = None


@dataclass
class ScheduledEvent:
    """A server scheduled event."""
    name: str
    description: str = ""
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: str = ""


@dataclass
class ServerKnowledge:
    """Complete knowledge snapshot for one guild."""
    guild_id: int
    guild_name: str
    description: str = ""
    member_count: int = 0
    channels: List[ChannelInfo] = field(default_factory=list)
    roles: List[RoleInfo] = field(default_factory=list)
    pinned_messages: List[PinnedMessage] = field(default_factory=list)
    events: List[ScheduledEvent] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    rules_text: str = ""
    last_crawled: Optional[str] = None
    setup_complete: bool = False

    def to_context_string(self) -> str:
        """Convert to a text string for LLM context / RAG."""
        parts = [
            f"# Server: {self.guild_name}",
            f"Description: {self.description}" if self.description else "",
            f"Members: {self.member_count}",
            "",
            "## Channels:",
        ]

        # Group channels by category
        by_category: dict = {}
        for ch in self.channels:
            cat = ch.category or "No Category"
            by_category.setdefault(cat, []).append(ch)

        for cat, chs in by_category.items():
            parts.append(f"\n### 📁 {cat}")
            for ch in chs:
                desc = f" — {ch.description}" if ch.description else ""
                icon = "🔊" if ch.type == "voice" else "#"
                parts.append(f"  {icon}{ch.name}{desc}")

        if self.roles:
            parts.append("\n## Roles:")
            for role in self.roles:
                if role.name != "@everyone":
                    parts.append(f"  🎭 {role.name} ({role.member_count} members)")

        if self.pinned_messages:
            parts.append("\n## Important Pinned Messages:")
            for pin in self.pinned_messages[:10]:
                parts.append(f"  📌 [{pin.channel_name}] {pin.content[:200]}")

        if self.events:
            parts.append("\n## Upcoming Events:")
            for evt in self.events:
                parts.append(f"  📅 {evt.name} — {evt.start_time or 'TBD'}")

        if self.rules_text:
            parts.append(f"\n## Server Rules:\n{self.rules_text[:500]}")

        return "\n".join(parts)

    def to_summary_string(self) -> str:
        """Compact summary for LLM context — ~200 tokens max."""
        cats = ", ".join(self.categories[:8]) if self.categories else "none"
        ch_count = len(self.channels)
        role_names = [r.name for r in self.roles[:10] if r.name != "@everyone"]
        roles_str = ", ".join(role_names) if role_names else "none"

        # Channel names grouped compact
        text_chs = [f"#{c.name}" for c in self.channels if c.type == "text"][:15]
        voice_chs = [f"🔊{c.name}" for c in self.channels if c.type == "voice"][:5]

        summary = (
            f"Server: {self.guild_name} | {self.member_count} members\n"
            f"Categories: {cats}\n"
            f"Channels ({ch_count}): {', '.join(text_chs[:10])}"
            f"{', ...' if len(text_chs) > 10 else ''}\n"
        )
        if voice_chs:
            summary += f"Voice: {', '.join(voice_chs)}\n"
        summary += f"Roles: {roles_str}\n"
        if self.rules_text:
            summary += f"Rules: {self.rules_text[:150]}\n"
        return summary
