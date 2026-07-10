"""Property test for CORS origins parsing in Config.

Validates: Requirements 9 (ALLOWED_ORIGINS env var parsing).
"""
import os
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st


def _reset_config_singleton():
    """Reset the Config singleton so it re-reads env vars on next instantiation."""
    from app import config as config_module
    old_instance = config_module.Config._instance
    config_module.Config._instance = None
    return old_instance


def _restore_config_singleton(old_instance):
    """Restore the Config singleton to a previously captured state."""
    from app import config as config_module
    config_module.Config._instance = old_instance


# Feature: optimization, Property 9: CORS origins parsing
# Validates: Requirements 9
@given(origins=st.lists(
    st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789-.",
        min_size=3,
        max_size=30,
    ),
    min_size=1,
    max_size=10,
))
@settings(max_examples=100)
def test_allowed_origins_parse_correctly(origins):
    """Property 9: comma-separated ALLOWED_ORIGINS env var parses to correct list.

    **Validates: Requirements 9**
    """
    origins_str = ",".join(origins)
    os.environ["ALLOWED_ORIGINS"] = origins_str
    old_instance = _reset_config_singleton()

    try:
        from app.config import Config
        cfg = Config()
        result = cfg.ALLOWED_ORIGINS
        expected = [o.strip() for o in origins_str.split(",") if o.strip()]
        assert result == expected, f"Expected {expected}, got {result}"
    finally:
        _restore_config_singleton(old_instance)
        os.environ.pop("ALLOWED_ORIGINS", None)


def test_allowed_origins_default_empty():
    """Without ALLOWED_ORIGINS env var, ALLOWED_ORIGINS defaults to [] (secure)."""
    os.environ.pop("ALLOWED_ORIGINS", None)
    old_instance = _reset_config_singleton()
    try:
        from app.config import Config
        cfg = Config()
        assert cfg.ALLOWED_ORIGINS == []
    finally:
        _restore_config_singleton(old_instance)


def test_allowed_origins_strips_whitespace():
    """Whitespace around origins is stripped correctly."""
    os.environ["ALLOWED_ORIGINS"] = "  http://localhost , https://example.com  "
    old_instance = _reset_config_singleton()
    try:
        from app.config import Config
        cfg = Config()
        assert cfg.ALLOWED_ORIGINS == ["http://localhost", "https://example.com"]
    finally:
        _restore_config_singleton(old_instance)
        os.environ.pop("ALLOWED_ORIGINS", None)


def test_allowed_origins_single_entry():
    """A single origin without commas is parsed as a one-element list."""
    os.environ["ALLOWED_ORIGINS"] = "https://myapp.com"
    old_instance = _reset_config_singleton()
    try:
        from app.config import Config
        cfg = Config()
        assert cfg.ALLOWED_ORIGINS == ["https://myapp.com"]
    finally:
        _restore_config_singleton(old_instance)
        os.environ.pop("ALLOWED_ORIGINS", None)
