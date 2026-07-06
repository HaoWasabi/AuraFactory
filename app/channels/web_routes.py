# app/channels/web_routes.py
"""
Web Routes — FastAPI router for OAuth, dashboard, and system endpoints.
Handles Discord OAuth2 flow, session management, and template rendering.
"""
import logging
import time
from typing import Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app.config.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["web"])

# Jinja2 templates
templates = Jinja2Templates(directory="frontend/templates")

# Session serializer (signed cookies)
_serializer = URLSafeTimedSerializer(settings.secret_key)

# Discord OAuth2 constants
DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_OAUTH_AUTHORIZE = "https://discord.com/api/oauth2/authorize"
DISCORD_OAUTH_TOKEN = "https://discord.com/api/oauth2/token"
DISCORD_OAUTH_SCOPES = "identify guilds"

# Session max age (7 days)
SESSION_MAX_AGE = 7 * 24 * 3600


# ================================================================
# Helper Functions
# ================================================================

def _create_session(user_data: dict, request: Request) -> str:
    """Create a signed session ID and store user data."""
    session_id = str(uuid4())
    signed = _serializer.dumps(session_id)

    # Store in app.state.session_store
    session_store = getattr(request.app.state, "session_store", {})
    session_store[session_id] = {
        **user_data,
        "created_at": time.time(),
    }
    request.app.state.session_store = session_store

    return signed


def _get_session(request: Request) -> Optional[dict]:
    """Retrieve and validate current session."""
    signed_id = request.cookies.get("session_id")
    if not signed_id:
        return None

    try:
        session_id = _serializer.loads(signed_id, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None

    session_store = getattr(request.app.state, "session_store", {})
    return session_store.get(session_id)


def _require_auth(request: Request) -> dict:
    """Get current user or raise redirect."""
    user = _get_session(request)
    if not user:
        raise HTTPException(status_code=302, headers={"Location": "/"})
    return user


# ================================================================
# Public Routes
# ================================================================

@router.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    """Serve login page. Redirect to dashboard if already logged in."""
    user = _get_session(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """Serve main dashboard. Requires authentication."""
    user = _get_session(request)
    if not user:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
    })


# ================================================================
# OAuth2 Flow
# ================================================================

@router.get("/auth/discord")
async def oauth_discord(request: Request):
    """Initiate Discord OAuth2 flow — redirect to Discord authorize page."""
    params = {
        "client_id": settings.discord_client_id,
        "redirect_uri": settings.discord_redirect_uri,
        "response_type": "code",
        "scope": DISCORD_OAUTH_SCOPES,
    }
    authorize_url = f"{DISCORD_OAUTH_AUTHORIZE}?" + "&".join(
        f"{k}={v}" for k, v in params.items()
    )
    return RedirectResponse(url=authorize_url)


@router.get("/auth/callback")
async def oauth_callback(request: Request, code: Optional[str] = None, error: Optional[str] = None):
    """
    Handle Discord OAuth2 callback.
    Exchange code for token → get user info → create session → redirect.
    """
    if error:
        logger.warning(f"OAuth error: {error}")
        return RedirectResponse(url="/?error=oauth_denied")

    if not code:
        return RedirectResponse(url="/?error=no_code")

    try:
        # Exchange code for access token
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                DISCORD_OAUTH_TOKEN,
                data={
                    "client_id": settings.discord_client_id,
                    "client_secret": settings.discord_client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.discord_redirect_uri,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if token_response.status_code != 200:
                logger.error(f"Token exchange failed: {token_response.text}")
                return RedirectResponse(url="/?error=token_failed")

            token_data = token_response.json()
            access_token = token_data["access_token"]

            # Get user info
            user_response = await client.get(
                f"{DISCORD_API_BASE}/users/@me",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if user_response.status_code != 200:
                logger.error(f"User info failed: {user_response.text}")
                return RedirectResponse(url="/?error=user_failed")

            user_data = user_response.json()

            # Get user guilds
            guilds_response = await client.get(
                f"{DISCORD_API_BASE}/users/@me/guilds",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            guilds = []
            if guilds_response.status_code == 200:
                all_guilds = guilds_response.json()
                # Filter to allowed guilds (or show all if no restriction)
                allowed_ids = settings.allowed_guild_ids
                if not allowed_ids:
                    guilds = all_guilds
                else:
                    guilds = [g for g in all_guilds if g["id"] in allowed_ids]

        # Build session user data
        session_user = {
            "id": user_data["id"],
            "username": user_data["username"],
            "discriminator": user_data.get("discriminator", "0"),
            "avatar": user_data.get("avatar"),
            "guilds": guilds,
            "is_admin": any(
                (int(g.get("permissions", 0)) & 0x8) == 0x8  # ADMINISTRATOR flag
                for g in guilds
            ),
            "current_guild_id": int(guilds[0]["id"]) if guilds else None,
            "access_token": access_token,
        }

        # Create session
        signed_session = _create_session(session_user, request)

        # Redirect to dashboard with session cookie
        response = RedirectResponse(url="/dashboard", status_code=302)
        response.set_cookie(
            key="session_id",
            value=signed_session,
            max_age=SESSION_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=not settings.debug,
        )
        return response

    except httpx.HTTPError as e:
        logger.error(f"OAuth HTTP error: {e}")
        return RedirectResponse(url="/?error=network_error")
    except Exception as e:
        logger.error(f"OAuth unexpected error: {e}", exc_info=True)
        return RedirectResponse(url="/?error=unknown")


@router.get("/auth/me")
async def auth_me(request: Request):
    """Return current user info + guilds as JSON."""
    user = _get_session(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return JSONResponse({
        "id": user["id"],
        "username": user["username"],
        "avatar": user.get("avatar"),
        "guilds": user.get("guilds", []),
        "is_admin": user.get("is_admin", False),
        "current_guild_id": user.get("current_guild_id"),
    })


@router.get("/auth/logout")
async def auth_logout(request: Request):
    """Clear session and redirect to login."""
    signed_id = request.cookies.get("session_id")
    if signed_id:
        try:
            session_id = _serializer.loads(signed_id, max_age=SESSION_MAX_AGE)
            session_store = getattr(request.app.state, "session_store", {})
            session_store.pop(session_id, None)
        except (BadSignature, SignatureExpired):
            pass

    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("session_id")
    return response


# ================================================================
# System Endpoints
# ================================================================

@router.get("/health")
async def health(request: Request):
    """System health for Render deployment."""
    start_time = getattr(request.app.state, "start_time", time.time())
    return JSONResponse({
        "status": "healthy",
        "uptime_seconds": round(time.time() - start_time, 2),
        "service": "aurafactory",
    })


@router.get("/metrics")
async def metrics_endpoint(request: Request):
    """Basic metrics JSON for monitoring."""
    from app.infra.observability import metrics as app_metrics

    stats = app_metrics.get_stats()
    return JSONResponse({
        "stats": stats,
        "timestamp": time.time(),
    })


@router.get("/api/status")
async def api_status(request: Request):
    """Quick status check."""
    bot_connected = False
    discord_adapter = getattr(request.app.state, "discord_adapter", None)
    if discord_adapter and discord_adapter.bot.is_ready():
        bot_connected = True

    return JSONResponse({
        "status": "operational",
        "bot_connected": bot_connected,
        "guilds": len(discord_adapter.bot.guilds) if bot_connected else 0,
    })


@router.get("/knowledge/{guild_id}")
async def get_guild_knowledge(guild_id: int, request: Request):
    """Get guild knowledge for dashboard display."""
    user = _get_session(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    knowledge_store = getattr(request.app.state, "knowledge_store", None)
    if not knowledge_store:
        raise HTTPException(status_code=503, detail="Knowledge store unavailable")

    try:
        knowledge = await knowledge_store.load(guild_id)
        if not knowledge:
            return JSONResponse({"guild_id": guild_id, "data": None})

        return JSONResponse({
            "guild_id": guild_id,
            "data": {
                "guild_name": knowledge.guild_name,
                "channels": len(knowledge.channels),
                "roles": len(knowledge.roles),
                "setup_complete": knowledge.setup_complete,
                "last_crawled": knowledge.last_crawled,
            },
        })
    except Exception as e:
        logger.error(f"Knowledge fetch error: {e}")
        raise HTTPException(status_code=500, detail="Lỗi tải dữ liệu guild.")
