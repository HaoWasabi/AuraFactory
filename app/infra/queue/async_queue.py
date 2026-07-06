"""Async task queue using asyncio.Queue."""

import asyncio
import logging
from typing import Any, Optional

from .base import QueueBase

logger = logging.getLogger(__name__)


class AsyncTaskQueue(QueueBase):
    """Async task queue backed by asyncio.Queue."""

    def __init__(self, maxsize: int = 0) -> None:
        """Initialize the queue.

        Args:
            maxsize: Maximum queue size (0 = unlimited).
        """
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=maxsize)
        logger.info("AsyncTaskQueue initialized (maxsize=%d)", maxsize)

    async def put(self, item: Any) -> None:
        """Add an item to the queue. Blocks if the queue is full."""
        await self._queue.put(item)
        logger.debug("Item added to queue (size=%d)", self._queue.qsize())

    async def get(self) -> Any:
        """Remove and return an item from the queue. Blocks if empty."""
        item = await self._queue.get()
        self._queue.task_done()
        return item

    async def get_nowait(self) -> Optional[Any]:
        """Remove and return an item without blocking. Returns None if empty."""
        try:
            item = self._queue.get_nowait()
            self._queue.task_done()
            return item
        except asyncio.QueueEmpty:
            return None

    def size(self) -> int:
        """Return the current number of items in the queue."""
        return self._queue.qsize()

    def is_empty(self) -> bool:
        """Check if the queue is empty."""
        return self._queue.empty()

    async def join(self) -> None:
        """Block until all items have been processed."""
        await self._queue.join()
