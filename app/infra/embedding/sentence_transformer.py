# app/infra/embedding/sentence_transformer.py
"""
Local embedding using sentence-transformers — Phase 1.
Phase 2: Replace with BedrockTitanEmbedding (same ABC).
"""
import asyncio
import logging
from typing import List

from app.infra.embedding.base import EmbeddingProvider

logger = logging.getLogger(__name__)


class SentenceTransformerEmbedding(EmbeddingProvider):
    """Local sentence-transformers embedding model."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self._dimension = self._model.get_sentence_embedding_dimension()
        logger.info(f"Embedding model loaded: {model_name} (dim={self._dimension})")

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, text: str) -> List[float]:
        """Embed a single text (runs in thread executor to not block event loop)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self._model.encode(text).tolist()
        )

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple texts in batch."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: [e.tolist() for e in self._model.encode(texts)]
        )
