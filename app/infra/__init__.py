# app/infra/__init__.py
"""
Layer 7 — Infrastructure Services.
Provides: LLM, Database, VectorStore, Embedding, Cache, Queue, Observability.
All services expose via ABC for Phase 1 → Phase 2 swap.

NOTE: Import from sub-modules directly to avoid circular imports.
Example: from app.infra.llm import get_provider, LLMProvider
"""
