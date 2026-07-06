# app/channels/base.py
"""
ChannelAdapterBase ABC — interface for all channel adapters.
Each adapter converts platform-specific messages to/from IncomingMessage/OutgoingMessage.
"""
from abc import ABC, abstractmethod
from typing import Callable, Awaitable

from app.models.messages import IncomingMessage, OutgoingMessage


class ChannelAdapterBase(ABC):
    """
    Abstract base for channel adapters.
    Adapts a specific platform (Discord, REST API, Web) to the unified message format.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Channel identifier (e.g. 'discord', 'api', 'web')."""
        ...

    @abstractmethod
    async def start(self) -> None:
        """Start the channel adapter (connect, listen)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel adapter (disconnect, cleanup)."""
        ...

    @abstractmethod
    async def send(self, message: OutgoingMessage) -> None:
        """Send a response back through this channel."""
        ...

    def set_handler(self, handler: Callable[[IncomingMessage], Awaitable[OutgoingMessage]]) -> None:
        """Set the message handler (called when a new message arrives)."""
        self._handler = handler
