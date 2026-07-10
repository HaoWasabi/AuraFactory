"""Tests for observability — logging, metrics, request context."""

import json
import logging

from app.core.observability import (
    JSONFormatter,
    set_request_context,
    get_request_id,
    generate_request_id,
)


class TestJSONFormatter:
    """Test structured JSON log output."""

    def test_basic_format(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Hello world", args=None, exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["msg"] == "Hello world"
        assert "ts" in parsed

    def test_includes_request_context(self):
        set_request_context("req-123", guild_id=456)
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Test", args=None, exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["request_id"] == "req-123"
        assert parsed["guild_id"] == 456


class TestRequestContext:
    def test_generate_request_id(self):
        rid = generate_request_id()
        assert len(rid) == 12
        assert rid.isalnum()

    def test_set_and_get(self):
        set_request_context("test-abc")
        assert get_request_id() == "test-abc"
