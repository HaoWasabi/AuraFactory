# app/infra/queue/__init__.py
"""Message queue infrastructure."""
from app.infra.queue.base import MessageQueue
from app.infra.queue.async_queue import AsyncQueueBackend

__all__ = ["MessageQueue", "AsyncQueueBackend"]
