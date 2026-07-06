# app/infra/embedding/__init__.py
"""Embedding infrastructure."""
from app.infra.embedding.base import EmbeddingProvider
from app.infra.embedding.sentence_transformer import SentenceTransformerEmbedding

__all__ = ["EmbeddingProvider", "SentenceTransformerEmbedding"]
