# app/infra/queue/base.py
"""
MessageQueue ABC.
Phase 1: asyncio.Queue. Phase 2: SQS.
"""
from abc import ABC, abstractmethod
from typing import Callable, Dict


class MessageQueue(ABC):
    """Abstract interface for message queue."""

    @abstractmethod
    async def publish(self, topic: str, message: dict, priority: int = 0) -> None:
        """Publish a message to a topic."""
        ...

    @abstractmethod
    async def subscribe(self, topic: str, handler: Callable) -> None:
        """Subscribe to a topic with a handler function."""
        ...

    @abstractmethod
    async def unsubscribe(self, topic: str) -> None:
        """Unsubscribe from a topic."""
        ...
