"""Sentence Transformer embedding placeholder (disabled in Phase 1)."""

import logging
from typing import List

from .base import EmbeddingBase

logger = logging.getLogger(__name__)


class DisabledError(Exception):
    """Raised when a disabled component is accessed."""

    def __init__(self, component: str = "Embedding") -> None:
        super().__init__(
            f"{component} is disabled in Phase 1. "
            f"Enable it by configuring ENABLE_TITAN_EMBEDDING=true or installing sentence-transformers."
        )


class SentenceTransformerEmbedding(EmbeddingBase):
    """Sentence Transformer embedding - disabled placeholder for Phase 1.

    All operations raise DisabledError. This will be implemented
    when embedding functionality is enabled in a later phase.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model_name = model_name
        logger.warning(
            "SentenceTransformerEmbedding instantiated but is disabled in Phase 1 (model=%s)",
            model_name,
        )

    async def embed_text(self, text: str) -> List[float]:
        """Disabled - raises DisabledError."""
        raise DisabledError("SentenceTransformerEmbedding.embed_text")

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Disabled - raises DisabledError."""
        raise DisabledError("SentenceTransformerEmbedding.embed_batch")
