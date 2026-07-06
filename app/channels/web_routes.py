# app/channels/web_routes.py
"""
Web Routes — Discord OAuth2 + Template Serving.
Handles login flow and serves the frontend pages.
"""
import logging
import secrets
from typing import Optional

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["web"])

DISCORD_API = "https://discord.com/api/v10"
DISCORD_OAUTH_AUTHORIZE = "https://discord.com/api/oauth2/authorize"
DISCORD_OAUTH_TOKEN = "https://discord.com/api/oauth2/token"


# ============================================================
# HELPERS
# ============================================================

async def discord_fetch(token: str, path: str) -> Optional[dict | list]:
    """Fetch from Discord API with bearer token."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{DISCORD_API}{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        logger.warning(f"Discord API {path} returned {resp.status_code}")
        return None


# ============================================================
# AUTH ROUTES
# ============================================================

@router.get("/auth/discord")
async def auth_discord(request: Request):
    """Redirect to Discord OAuth2 authorize page."""
    if not settings.discord_client_id:
        return JSONResponse(
            content={"error": "DISCORD_CLIENT_ID not configured"},
            status_code=500,
        )

    params = {
        "client_id": settings.discord_client_id,
        "redirect_uri": settings.discord_redirect_uri,
        "response_type": "code",
        "scope": "identify email guilds",
    }
    url = f"{DISCORD_OAUTH_AUTHORIZE}?" + "&".join(f"{k}={v}" for k, v in params.items())
    return RedirectResponse(url=url)


@router.get("/auth/callback")
async def auth_callback(request: Request, code: str = ""):
    """Handle Discord OAuth2 callback."""
    if not code:
        return RedirectResponse(url="/")

    # Exchange code for token
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            DISCORD_OAUTH_TOKEN,
            data={
                "client_id": settings.discord_client_id,
                "client_secret": settings.discord_client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.discord_redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )

    if resp.status_code != 200:
        logger.error(f"Token exchange failed: {resp.status_code} {resp.text}")
        return RedirectResponse(url="/")

    token_data = resp.json()
    access_token = token_data.get("access_token")

    if not access_token:
        return RedirectResponse(url="/")

    # Store token in session
    request.session["discord_token"] = access_token
    request.session["token_type"] = token_data.get("token_type", "Bearer")

    return RedirectResponse(url="/dashboard")


@router.get("/auth/me")
async def auth_me(request: Request):
    """Get current user info + guilds (called by dashboard JS)."""
    token = request.session.get("discord_token")
    if not token:
        return JSONResponse(content={"error": "Not authenticated"}, status_code=401)

    user = await discord_fetch(token, "/users/@me")
    if not user:
        request.session.clear()
        return JSONResponse(content={"error": "Token expired"}, status_code=401)

    guilds = await discord_fetch(token, "/users/@me/guilds") or []

    return JSONResponse(content={
        "user": user,
        "guilds": guilds,
    })


@router.get("/auth/logout")
async def auth_logout(request: Request):
    """Clear session and redirect to login."""
    request.session.clear()
    return RedirectResponse(url="/")


# ============================================================
# PAGE ROUTES
# ============================================================

@router.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def page_login(request: Request):
    """Login page — redirect to dashboard if already authenticated."""
    token = request.session.get("discord_token")
    if token:
        # Verify token is still valid
        user = await discord_fetch(token, "/users/@me")
        if user:
            return RedirectResponse(url="/dashboard")
        request.session.clear()

    return request.app.state.templates.TemplateResponse("login.html", {"request": request})


@router.get("/dashboard", response_class=HTMLResponse)
async def page_dashboard(request: Request):
    """Dashboard page — requires authentication."""
    token = request.session.get("discord_token")
    if not token:
        return RedirectResponse(url="/")

    return request.app.state.templates.TemplateResponse("dashboard.html", {"request": request})
