# app/infra/queue/async_queue.py
"""
asyncio.PriorityQueue-based message queue — Phase 1.
Phase 2: Replace with SQSBackend (same ABC).
"""
import asyncio
import logging
from typing import Callable, Dict

from app.infra.queue.base import MessageQueue

logger = logging.getLogger(__name__)


class AsyncQueueBackend(MessageQueue):
    """In-process async message queue using asyncio.PriorityQueue."""

    def __init__(self, max_size: int = 1000):
        self._queues: Dict[str, asyncio.PriorityQueue] = {}
        self._handlers: Dict[str, Callable] = {}
        self._consumers: Dict[str, asyncio.Task] = {}
        self._max_size = max_size
        self._running = True

    async def publish(self, topic: str, message: dict, priority: int = 0) -> None:
        if topic not in self._queues:
            self._queues[topic] = asyncio.PriorityQueue(maxsize=self._max_size)

        await self._queues[topic].put((priority, message))
        logger.debug(f"Published to '{topic}' (priority={priority})")

    async def subscribe(self, topic: str, handler: Callable) -> None:
        self._handlers[topic] = handler
        if topic not in self._queues:
            self._queues[topic] = asyncio.PriorityQueue(maxsize=self._max_size)

        # Start consumer task
        if topic not in self._consumers or self._consumers[topic].done():
            self._consumers[topic] = asyncio.create_task(self._consume(topic))
            logger.info(f"Consumer started for topic '{topic}'")

    async def unsubscribe(self, topic: str) -> None:
        if topic in self._consumers:
            self._consumers[topic].cancel()
            del self._consumers[topic]
        self._handlers.pop(topic, None)
        logger.info(f"Unsubscribed from topic '{topic}'")

    async def _consume(self, topic: str) -> None:
        """Background consumer loop."""
        queue = self._queues[topic]
        while self._running:
            try:
                priority, message = await asyncio.wait_for(queue.get(), timeout=1.0)
                handler = self._handlers.get(topic)
                if handler:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            await handler(message)
                        else:
                            handler(message)
                    except Exception as e:
                        logger.error(f"Handler error for '{topic}': {e}")
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def shutdown(self) -> None:
        """Gracefully stop all consumers."""
        self._running = False
        for task in self._consumers.values():
            task.cancel()
        self._consumers.clear()
