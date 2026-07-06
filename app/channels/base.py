# app/channels/base.py
"""
Channel Adapter Base — abstract interface for all input/output adapters.
All channels (Discord, API, Web) implement this protocol.
"""
from abc import ABC, abstractmethod
from typing import Any

from app.models.messages import IncomingMessage, OutgoingMessage


class ChannelAdapterBase(ABC):
    """
    Abstract base for all channel adapters.

    Each adapter must:
    1. Receive raw platform input and convert to IncomingMessage
    2. Send OutgoingMessage back to the platform in correct format
    3. Start its event loop / listener
    """

    @abstractmethod
    async def receive(self, raw_input: Any) -> IncomingMessage:
        """
        Convert platform-specific raw input to standardized IncomingMessage.

        Args:
            raw_input: Platform-specific message object (e.g., nextcord.Message, dict)

        Returns:
            IncomingMessage ready for gateway processing.
        """
        ...

    @abstractmethod
    async def send(self, message: OutgoingMessage, destination: Any) -> None:
        """
        Send a response back to the platform.

        Args:
            message: Standardized outgoing message.
            destination: Platform-specific target (channel, user, etc.)
        """
        ...

    @abstractmethod
    async def start(self) -> None:
        """
        Start the adapter's event loop or listener.
        For Discord: connect bot. For API: included via FastAPI router.
        """
        ...
