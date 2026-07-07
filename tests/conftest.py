"""Pytest fixtures shared across the test suite."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.llm.base import LLMResponse, UsageStats


@pytest.fixture
def mock_db():
    """AsyncMock for Database with all standard query methods."""
    db = MagicMock()
    db.execute = AsyncMock(return_value="OK")
    db.fetch = AsyncMock(return_value=[])
    db.fetchrow = AsyncMock(return_value=None)
    db.fetchval = AsyncMock(return_value=None)

    # transaction() is an async context manager
    transaction_cm = MagicMock()
    transaction_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    transaction_cm.__aexit__ = AsyncMock(return_value=False)
    db.transaction = MagicMock(return_value=transaction_cm)

    return db


@pytest.fixture
def mock_llm():
    """AsyncMock for BaseLLM whose generate() returns a standard LLMResponse."""
    llm = MagicMock()
    llm.provider_name = "test-provider"
    llm.generate = AsyncMock(
        return_value=LLMResponse(
            content="test",
            usage=UsageStats(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        )
    )
    return llm
