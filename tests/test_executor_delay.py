"""Unit test: asyncio.sleep(0.3) is called between steps but not after the last step."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import uuid


def _make_plan_record(request_id):
    """Return a dict-like object that supports both subscript and .get() access."""
    data = {
        "request_id": request_id,
        "guild_id": 123456,
        "user_id": 789,
        "risk_level": "LOW",
    }
    record = MagicMock()
    record.__getitem__ = MagicMock(side_effect=lambda k: data[k])
    record.get = MagicMock(side_effect=lambda k, d=None: data.get(k, d))
    return record


def _make_step_dict(n):
    """Return a plain dict for a step — required because execute_plan calls dict(step)."""
    return {
        "id": str(uuid.uuid4()),
        "tool_name": f"discord.test.step{n}",
        "tool_params": "{}",
        "description": f"Step {n}",
        "risk_level": "LOW",
        "step_number": n,
    }


def _success_response():
    r = MagicMock()
    r.success = True
    r.result = {"status": "ok"}
    r.error = None
    return r


@pytest.mark.asyncio
async def test_sleep_called_between_steps_not_after_last():
    """asyncio.sleep(0.3) must be called exactly N-1 times for N successful steps."""
    from app.services.executor_service import ExecutorService

    db = MagicMock()
    db.fetchrow = AsyncMock()
    db.fetch = AsyncMock()
    db.execute = AsyncMock(return_value="UPDATE 1")

    mcp_client = MagicMock()
    mcp_client.call_tool = AsyncMock(return_value=_success_response())

    llm = MagicMock()
    context_service = MagicMock()
    context_service.get_server_context = AsyncMock(return_value={})
    context_service.invalidate = AsyncMock()

    executor = ExecutorService(db, mcp_client, llm, context_service)

    plan_id = str(uuid.uuid4())
    request_id = str(uuid.uuid4())

    db.fetchrow.return_value = _make_plan_record(request_id)
    # Use plain dicts so dict(step) works correctly inside execute_plan
    db.fetch.return_value = [_make_step_dict(i) for i in range(1, 4)]  # 3 steps

    with patch("app.services.executor_service.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await executor.execute_plan(plan_id)

    assert result["status"] == "completed"
    assert result["completed_steps"] == 3
    # 3 steps → sleep called exactly 2 times (not after last step)
    assert mock_sleep.call_count == 2
    mock_sleep.assert_called_with(0.3)


@pytest.mark.asyncio
async def test_sleep_not_called_for_single_step():
    """With only 1 step, sleep must NOT be called at all."""
    from app.services.executor_service import ExecutorService

    db = MagicMock()
    db.fetchrow = AsyncMock()
    db.fetch = AsyncMock()
    db.execute = AsyncMock(return_value="UPDATE 1")

    mcp_client = MagicMock()
    mcp_client.call_tool = AsyncMock(return_value=_success_response())

    llm = MagicMock()
    context_service = MagicMock()
    context_service.get_server_context = AsyncMock(return_value={})
    context_service.invalidate = AsyncMock()

    executor = ExecutorService(db, mcp_client, llm, context_service)

    plan_id = str(uuid.uuid4())
    request_id = str(uuid.uuid4())

    plan_record = MagicMock()
    plan_record.__getitem__ = MagicMock(side_effect=lambda k: {
        "request_id": request_id, "guild_id": 111, "user_id": 222, "risk_level": "LOW",
    }.get(k))
    plan_record.get = MagicMock(side_effect=lambda k, d=None: {
        "request_id": request_id, "guild_id": 111, "user_id": 222, "risk_level": "LOW",
    }.get(k, d))

    db.fetchrow.return_value = plan_record
    db.fetch.return_value = [_make_step_dict(1)]

    with patch("app.services.executor_service.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await executor.execute_plan(plan_id)

    assert result["status"] == "completed"
    assert result["completed_steps"] == 1
    assert mock_sleep.call_count == 0
