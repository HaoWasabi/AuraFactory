"""Unit tests for AuthService.get_user_token() expiry check."""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

from app.services.auth_service import AuthService


def make_auth_service():
    """Build an AuthService with a mocked Database."""
    db = MagicMock()
    db.fetchrow = AsyncMock()
    db.execute = AsyncMock()
    return AuthService(db), db


def make_row(token: str, expires_at):
    """Create a mock asyncpg-style record row."""
    row = MagicMock()
    row.__getitem__ = MagicMock(
        side_effect=lambda k: {
            "access_token_enc": token,
            "token_expires_at": expires_at,
        }[k]
    )
    return row


@pytest.mark.asyncio
async def test_expired_token_returns_none(caplog):
    """Token expired in the past → returns None and logs a warning."""
    import logging

    auth, db = make_auth_service()
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    db.fetchrow.return_value = make_row("enc_token_xyz", past)

    with caplog.at_level(logging.WARNING):
        result = await auth.get_user_token(12345)

    assert result is None
    assert any("expired" in r.message.lower() for r in caplog.records)


@pytest.mark.asyncio
async def test_valid_token_returns_token():
    """Token expires in the future → returns the token string."""
    auth, db = make_auth_service()
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    db.fetchrow.return_value = make_row("valid_token_abc", future)

    result = await auth.get_user_token(12345)
    assert result == "valid_token_abc"


@pytest.mark.asyncio
async def test_no_expiry_field_returns_token():
    """token_expires_at is None → backward compat, token is returned."""
    auth, db = make_auth_service()
    db.fetchrow.return_value = make_row("legacy_token", None)

    result = await auth.get_user_token(12345)
    assert result == "legacy_token"


@pytest.mark.asyncio
async def test_user_not_found_returns_none():
    """No row in DB → returns None."""
    auth, db = make_auth_service()
    db.fetchrow.return_value = None

    result = await auth.get_user_token(99999)
    assert result is None


@pytest.mark.asyncio
async def test_token_expiring_exactly_now_returns_none():
    """Token expiry == now is treated as expired (boundary condition)."""
    auth, db = make_auth_service()
    # expires_at <= now should be treated as expired per implementation
    now = datetime.now(timezone.utc)
    db.fetchrow.return_value = make_row("boundary_token", now - timedelta(seconds=1))

    result = await auth.get_user_token(12345)
    assert result is None


@pytest.mark.asyncio
async def test_get_user_token_queries_correct_user_id():
    """get_user_token passes the user_id to the DB query."""
    auth, db = make_auth_service()
    db.fetchrow.return_value = None

    await auth.get_user_token(777)

    db.fetchrow.assert_called_once()
    call_args = db.fetchrow.call_args
    # Second positional arg should be the user_id
    assert call_args.args[1] == 777
