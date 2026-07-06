"""Base queue interface."""

from abc import ABC, abstractmethod
from typing import Any, Optional


class QueueBase(ABC):
    """Abstract base class for task queue implementations."""

    @abstractmethod
    async def put(self, item: Any) -> None:
        """Add an item to the queue."""
        ...

    @abstractmethod
    async def get(self) -> Any:
        """Remove and return an item from the queue. Blocks if empty."""
        ...

    @abstractmethod
    async def get_nowait(self) -> Optional[Any]:
        """Remove and return an item without blocking. Returns None if empty."""
        ...

    @abstractmethod
    def size(self) -> int:
        """Return the current number of items in the queue."""
        ...

    @abstractmethod
    def is_empty(self) -> bool:
        """Check if the queue is empty."""
        ...
