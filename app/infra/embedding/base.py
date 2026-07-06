# app/infra/embedding/base.py
"""
EmbeddingProvider ABC.
Phase 1: sentence-transformers (local). Phase 2: AWS Titan Embed.
"""
from abc import ABC, abstractmethod
from typing import List


class EmbeddingProvider(ABC):
    """Abstract interface for text embedding."""

    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """Embed a single text string."""
        ...

    @abstractmethod
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple texts in a batch."""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding dimension."""
        ...
