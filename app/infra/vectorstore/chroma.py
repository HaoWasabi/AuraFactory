# app/infra/vectorstore/chroma.py
"""
ChromaDB implementation — Phase 1 vector store.
Phase 2: Replace with OpenSearchVectorStore (same ABC).
"""
import logging
from typing import List, Optional

from app.infra.vectorstore.base import VectorStore

logger = logging.getLogger(__name__)


class ChromaVectorStore(VectorStore):
    """ChromaDB persistent vector store."""

    def __init__(self, path: str = "./data/chroma"):
        import chromadb

        self._client = chromadb.PersistentClient(path=path)
        logger.info(f"ChromaDB initialized at {path}")

    def _get_collection(self, name: str):
        """Get or create a collection."""
        return self._client.get_or_create_collection(name)

    async def add(
        self,
        collection: str,
        id: str,
        text: str,
        embedding: List[float],
        metadata: Optional[dict] = None,
    ) -> None:
        col = self._get_collection(collection)
        col.add(
            ids=[id],
            documents=[text],
            embeddings=[embedding],
            metadatas=[metadata or {}],
        )

    async def add_batch(
        self,
        collection: str,
        ids: List[str],
        texts: List[str],
        embeddings: List[List[float]],
        metadatas: Optional[List[dict]] = None,
    ) -> None:
        col = self._get_collection(collection)
        col.add(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas or [{} for _ in ids],
        )

    async def query(
        self,
        collection: str,
        embedding: List[float],
        top_k: int = 5,
        filter: Optional[dict] = None,
    ) -> List[dict]:
        col = self._get_collection(collection)
        kwargs = {
            "query_embeddings": [embedding],
            "n_results": top_k,
        }
        if filter:
            kwargs["where"] = filter

        results = col.query(**kwargs)
        return self._format_results(results)

    async def delete(self, collection: str, id: str) -> None:
        col = self._get_collection(collection)
        col.delete(ids=[id])

    async def delete_collection(self, collection: str) -> None:
        self._client.delete_collection(collection)

    async def count(self, collection: str) -> int:
        col = self._get_collection(collection)
        return col.count()

    def _format_results(self, results: dict) -> List[dict]:
        """Convert ChromaDB results to standardized format."""
        formatted = []
        if not results or not results.get("ids"):
            return formatted

        ids = results["ids"][0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for i, doc_id in enumerate(ids):
            formatted.append({
                "id": doc_id,
                "text": documents[i] if i < len(documents) else "",
                "metadata": metadatas[i] if i < len(metadatas) else {},
                "score": 1.0 - (distances[i] if i < len(distances) else 0.0),
            })

        return formatted
