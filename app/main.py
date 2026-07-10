"""
AuraFactory — Main Entrypoint.
FastAPI application with lifespan managing all services.
Architecture: Config → Infra → MCP → Connectors → Services → Interfaces
"""
import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings

# Choose observability backend
if settings.LLM_PROVIDER == "bedrock" or settings.DATABASE_BACKEND == "dynamodb":
    from app.core.observability_aws import configure_logging, metrics_endpoint, generate_request_id, set_request_context
else:
    from app.core.observability import configure_logging, metrics_endpoint, generate_request_id, set_request_context


# Configure structured logging
configure_logging(
    level=settings.LOG_LEVEL,
    json_output=not settings.DEBUG,  # Human-readable in debug mode
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — initialize and teardown all services."""
    logger.info("[START] AuraFactory starting up...")
    start_time = time.time()

    # === Infrastructure ===
    # Choose database backend
    if settings.DATABASE_BACKEND == "dynamodb":
        from app.database_dynamo import Database
        logger.info("[DB] Using DynamoDB backend (table: %s)", settings.DYNAMODB_TABLE_NAME)
    else:
        from app.database import Database
    db = Database()
    for attempt in range(5):
        try:
            await db.connect()
            await db.run_migrations("migrations")
            logger.info("[OK] Database connected + migrations applied")
            break
        except Exception as e:
            if attempt < 4:
                wait = 2 ** attempt
                logger.warning("[WARN] DB connection attempt %d failed: %s — retrying in %ds...", attempt + 1, e, wait)
                await asyncio.sleep(wait)
            else:
                logger.error("[ERROR] Database connection failed after 5 attempts: %s", e)
                raise RuntimeError(f"Cannot start without database: {e}")

    # === LLM ===
    from app.llm import get_llm
    llm = None
    try:
        if settings.LLM_PROVIDER == "bedrock":
            llm = get_llm(
                provider="bedrock",
                model=settings.BEDROCK_MODEL_ID,
                region=settings.AWS_REGION,
            )
            logger.info("[OK] LLM provider: bedrock (%s @ %s)", settings.BEDROCK_MODEL_ID, settings.AWS_REGION)
        elif settings.LLM_PROVIDER == "ollama":
            llm = get_llm(
                provider="ollama",
                model=settings.OLLAMA_MODEL,
                base_url=settings.OLLAMA_BASE_URL,
            )
            logger.info("[OK] LLM provider: ollama (%s @ %s)", settings.OLLAMA_MODEL, settings.OLLAMA_BASE_URL)
        else:
            llm = get_llm(
                provider=settings.LLM_PROVIDER,
                model=settings.GEMINI_MODEL,
                api_key=settings.GEMINI_API_KEY,
            )
            logger.info("[OK] LLM provider: %s (%s)", settings.LLM_PROVIDER, settings.GEMINI_MODEL)
    except Exception as e:
        logger.error("[ERROR] LLM initialization FAILED: %s", e, exc_info=True)
        logger.error("   AI features will NOT work.")

    # === MCP ===
    from app.mcp import MCPClient
    from app.mcp.servers.discord_server import DiscordMCPServer

    mcp_client = MCPClient()
    discord_mcp_server = DiscordMCPServer()
    mcp_client.register_server(discord_mcp_server)
    logger.info("[OK] MCP client ready (discord server registered, awaiting bot)")

    # === Services ===
    from app.services.context_service import ContextService
    from app.services.auth_service import AuthService
    from app.services.guild_sync_service import GuildSyncService
    from app.services.unified_agent import UnifiedAgent

    context_service = ContextService(db, mcp_client)
    auth_service = AuthService(db)
    guild_sync_service = GuildSyncService(db)

    # Load SpecRegistry for safety layers (non-blocking — skip if file missing)
    registry = None
    try:
        from app.core.spec_loader import SpecRegistry
        registry = SpecRegistry.load()
        logger.info("[OK] SpecRegistry loaded: %d tools", len(registry.get_all_tools()))
    except Exception as e:
        logger.warning("[WARN] SpecRegistry not loaded (safety features degraded): %s", e)

    # UnifiedAgent v6 — with db + registry for full safety layers
    unified_agent = UnifiedAgent(llm, mcp_client, context_service, db=db, registry=registry) if llm else None

    services = {
        "context_service": context_service,
        "auth_service": auth_service,
        "guild_sync_service": guild_sync_service,
        "unified_agent": unified_agent,
        "_mcp_client": mcp_client,
        "_db": db,
    }
    logger.info("[OK] All services initialized")

    # === Interfaces ===
    from app.interfaces import DiscordBot, create_api_router

    # API routes
    api_router = create_api_router(services)
    app.include_router(api_router)
    logger.info("[OK] API routes registered")

    # Discord bot (background task)
    bot = None
    bot_task = None
    if settings.DISCORD_TOKEN:
        bot = DiscordBot(services=services, mcp_discord_server=discord_mcp_server)
        bot_task = asyncio.create_task(_run_bot(bot))
        logger.info("[BOT] Discord bot starting in background...")
    else:
        logger.warning("[WARN] No DISCORD_TOKEN — bot will not connect")

    # Store refs on app.state for access in routes if needed
    app.state.db = db
    app.state.services = services
    app.state.bot = bot
    app.state.start_time = time.time()

    elapsed = time.time() - start_time
    logger.info("[OK] AuraFactory ready in %.2fs", elapsed)

    yield  # App is running

    # === Shutdown ===
    logger.info("[STOP] AuraFactory shutting down...")
    if bot:
        await bot.close()
    if bot_task and not bot_task.done():
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass
    await db.disconnect()
    logger.info("[BYE] AuraFactory stopped.")


async def _run_bot(bot):
    """Run Discord bot with error handling."""
    try:
        await bot.start(settings.DISCORD_TOKEN)
    except Exception as e:
        logger.error("Discord bot error: %s", e, exc_info=True)


# === FastAPI App ===
app = FastAPI(
    title="AuraFactory",
    description="AI-powered Discord server management",
    version="6.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Security Headers Middleware ===
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if not settings.DEBUG:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

app.add_middleware(SecurityHeadersMiddleware)


# === Request ID Middleware ===
class RequestIDMiddleware(BaseHTTPMiddleware):
    """Inject X-Request-ID into every request for tracing."""
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", generate_request_id())
        set_request_context(request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

app.add_middleware(RequestIDMiddleware)


# === Static files + Page routes ===
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")


@app.get("/")
async def serve_index():
    return FileResponse("frontend/index.html", headers={"Cache-Control": "no-cache, no-store"})

@app.head("/")
async def head_index():
    """Health check probe (Render sends HEAD /)."""
    return Response(status_code=200)


@app.get("/login")
async def serve_login():
    return FileResponse("frontend/templates/login.html", headers={"Cache-Control": "no-cache, no-store"})


@app.get("/dashboard")
async def serve_dashboard():
    return FileResponse(
        "frontend/templates/dashboard.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


@app.get("/auth/callback")
async def serve_callback():
    return FileResponse("frontend/templates/callback.html", headers={"Cache-Control": "no-cache, no-store"})


@app.get("/metrics")
async def prometheus_metrics():
    return await metrics_endpoint()


@app.get("/health")
async def health():
    """Detailed health check with dependency status."""
    db_ok = False
    try:
        if hasattr(app.state, 'db') and app.state.db and app.state.db.pool:
            await app.state.db.fetchval("SELECT 1")
            db_ok = True
    except Exception:
        pass

    bot_ready = False
    if hasattr(app.state, 'bot') and app.state.bot:
        bot_ready = app.state.bot.is_ready() if hasattr(app.state.bot, 'is_ready') else False

    status = "healthy" if db_ok else "degraded"
    return {
        "status": status,
        "service": "AuraFactory",
        "version": "6.0",
        "dependencies": {
            "database": "connected" if db_ok else "disconnected",
            "discord_bot": "ready" if bot_ready else "not_ready",
        },
    }
