# app/knowledge/__init__.py
"""
Server Knowledge Store — crawl, store, and query per-guild server information.
Used by Assistant mode for Q&A and onboarding recommendations.
"""
from app.knowledge.store import ServerKnowledgeStore
from app.knowledge.crawler import ServerCrawler

__all__ = ["ServerKnowledgeStore", "ServerCrawler"]
