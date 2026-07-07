"""Unit tests for non-blocking execution in API routes (task 10.5)."""
import sys
import pytest
import uuid
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def _make_services(plan_id=None):
    plan_id = plan_id or str(uuid.uuid4())

    db = MagicMock()
    db.fetchrow = AsyncMock(return_value=None)
    db.fetch = AsyncMock(return_value=[])
    db.execute = AsyncMock(return_value="OK")

    approval_service = MagicMock()
    approval_service.db = db
    approval_service.approve_plan = AsyncMock(return_value={"ok": True, "plan_id": plan_id})
    approval_service.reject_plan = AsyncMock(return_value={"ok": True})
    approval_service.get_pending_approval = AsyncMock(return_value=None)

    executor_service = MagicMock()
    executor_service.execute_plan = AsyncMock(return_value={"status": "completed"})

    guild_sync_service = MagicMock()
    guild_sync_service.db = db
    guild_sync_service.get_bot_invite_url = MagicMock(return_value="https://discord.com/invite")
    guild_sync_service.sync_user_guilds = AsyncMock(return_value=[])
    guild_sync_service.get_user_guilds = AsyncMock(return_value=[])

    request_service = MagicMock()
    request_service.create_request = AsyncMock(return_value={"ok": True, "request_id": str(uuid.uuid4())})
    request_service.update_status = AsyncMock()

    classifier_service = MagicMock()
    classifier_service.classify = AsyncMock(return_value={"intent": "setup", "tool_mode": "action", "lang": "vi", "confidence": 0.9})

    planner_service = MagicMock()
    planner_service.generate_plan = AsyncMock(return_value={
        "ok": True, "plan_id": plan_id, "description": "test",
        "steps": [], "risk_level": "LOW", "status": "approved", "auto_approved": True,
    })

    query_service = MagicMock()
    query_service.answer = AsyncMock(return_value="answer")

    auth_service = MagicMock()
    auth_service.get_oauth_url = MagicMock(return_value="https://discord.com/oauth")
    auth_service.exchange_code = AsyncMock(return_value=None)

    return {
        "auth_service": auth_service,
        "guild_sync_service": guild_sync_service,
        "request_service": request_service,
        "classifier_service": classifier_service,
        "planner_service": planner_service,
        "approval_service": approval_service,
        "executor_service": executor_service,
        "query_service": query_service,
        "context_service": MagicMock(),
    }, plan_id


@pytest.mark.asyncio
async def test_background_task_helper_logs_error_on_exception():
    """_run_execution_background catches exceptions, logs ERROR, does not raise."""
    from app.interfaces.api_routes import _run_execution_background

    executor = MagicMock()
    executor.execute_plan = AsyncMock(side_effect=RuntimeError("boom"))

    with patch("app.interfaces.api_routes.logger") as mock_logger:
        await _run_execution_background(executor, "bad-plan-id")

    mock_logger.error.assert_called_once()
    logged_msg = str(mock_logger.error.call_args)
    assert "bad-plan-id" in logged_msg


@pytest.mark.asyncio
async def test_background_task_helper_succeeds_silently():
    """_run_execution_background completes without error when execute_plan succeeds."""
    from app.interfaces.api_routes import _run_execution_background

    executor = MagicMock()
    executor.execute_plan = AsyncMock(return_value={"status": "completed"})

    await _run_execution_background(executor, str(uuid.uuid4()))
    executor.execute_plan.assert_called_once()


@pytest.mark.asyncio
async def test_approval_endpoint_non_blocking():
    """POST /api/approval approve → returns {status: executing} without awaiting execute_plan."""
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from app.interfaces.api_routes import create_api_router

    services, plan_id = _make_services()
    app = FastAPI()
    app.include_router(create_api_router(services))

    with patch("app.interfaces.api_routes.asyncio.create_task") as mock_create_task:
        mock_create_task.return_value = MagicMock()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/approval", json={
                "plan_id": plan_id,
                "action": "approve",
                "user_id": "12345",
            })

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["status"] == "executing"
    assert data["plan_id"] == plan_id
    # execute_plan must NOT have been called directly
    services["executor_service"].execute_plan.assert_not_called()
    mock_create_task.assert_called_once()


@pytest.mark.asyncio
async def test_execution_status_endpoint_not_found():
    """GET /api/execution/{plan_id}/status with unknown plan_id → 404."""
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from app.interfaces.api_routes import create_api_router

    services, _ = _make_services()
    # DB returns None for fetchrow (plan not found)
    services["approval_service"].db.fetchrow = AsyncMock(return_value=None)
    app = FastAPI()
    app.include_router(create_api_router(services))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/execution/{uuid.uuid4()}/status")

    assert resp.status_code == 404
