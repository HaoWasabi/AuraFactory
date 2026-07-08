"""
AuraFactory — Main Entrypoint.
FastAPI application with lifespan managing all services.
Architecture: Config → Infra → MCP → Connectors → Services → Interfaces
"""
import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response

from app.config import settings

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — initialize and teardown all services."""
    logger.info("🚀 AuraFactory starting up...")
    start_time = time.time()

    # === Infrastructure ===
    from app.database import Database
    db = Database()
    for attempt in range(5):
        try:
            await db.connect()
            await db.run_migrations("migrations")
            logger.info("✅ Database connected + migrations applied")

            # Cleanup stuck requests from previous crash/restart
            cleaned = await db.execute(
                """UPDATE requests SET status = 'failed', error_message = 'Server restarted', completed_at = NOW()
                   WHERE status IN ('planned', 'awaiting_approval', 'executing')"""
            )
            if cleaned and 'UPDATE' in cleaned and cleaned != 'UPDATE 0':
                logger.info("🧹 Cleaned up stuck requests: %s", cleaned)
            break
        except Exception as e:
            if attempt < 4:
                wait = 2 ** attempt
                logger.warning("⚠️ DB connection attempt %d failed: %s — retrying in %ds...", attempt + 1, e, wait)
                await asyncio.sleep(wait)
            else:
                logger.error("❌ Database connection failed after 5 attempts: %s", e)
                raise RuntimeError(f"Cannot start without database: {e}")

    # === LLM ===
    from app.llm import get_llm
    llm = None
    try:
        llm = get_llm(
            provider=settings.LLM_PROVIDER,
            model=settings.GEMINI_MODEL,
            api_key=settings.GEMINI_API_KEY,
        )
        logger.info("✅ LLM provider: %s (%s)", settings.LLM_PROVIDER, settings.GEMINI_MODEL)
    except Exception as e:
        logger.error("❌ LLM initialization FAILED: %s", e, exc_info=True)
        logger.error("   AI features will NOT work.")

    # === MCP ===
    from app.mcp import MCPClient
    from app.mcp.servers.discord_server import DiscordMCPServer

    mcp_client = MCPClient()
    discord_mcp_server = DiscordMCPServer()
    mcp_client.register_server(discord_mcp_server)
    logger.info("✅ MCP client ready (discord server registered, awaiting bot)")

    # === Services ===
    from app.services.context_service import ContextService
    from app.services.auth_service import AuthService
    from app.services.guild_sync_service import GuildSyncService
    from app.services.unified_agent import UnifiedAgent

    context_service = ContextService(db, mcp_client)
    auth_service = AuthService(db)
    guild_sync_service = GuildSyncService(db)
    unified_agent = UnifiedAgent(llm, mcp_client, context_service) if llm else None

    services = {
        "context_service": context_service,
        "auth_service": auth_service,
        "guild_sync_service": guild_sync_service,
        "unified_agent": unified_agent,
        "_mcp_client": mcp_client,
        "_db": db,
    }
    logger.info("✅ All services initialized")

    # === Interfaces ===
    from app.interfaces import DiscordBot, create_api_router

    # API routes
    api_router = create_api_router(services)
    app.include_router(api_router)
    logger.info("✅ API routes registered")

    # Discord bot (background task)
    bot = None
    bot_task = None
    if settings.DISCORD_TOKEN:
        bot = DiscordBot(services=services, mcp_discord_server=discord_mcp_server)
        bot_task = asyncio.create_task(_run_bot(bot))
        logger.info("🤖 Discord bot starting in background...")
    else:
        logger.warning("⚠️ No DISCORD_TOKEN — bot will not connect")

    # Store refs on app.state for access in routes if needed
    app.state.db = db
    app.state.services = services
    app.state.bot = bot

    elapsed = time.time() - start_time
    logger.info("✅ AuraFactory ready in %.2fs", elapsed)

    yield  # App is running

    # === Shutdown ===
    logger.info("🛑 AuraFactory shutting down...")
    if bot:
        await bot.close()
    if bot_task and not bot_task.done():
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass
    await db.disconnect()
    logger.info("👋 AuraFactory stopped.")


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


@app.get("/health")
async def health():
    return {"status": "ok", "service": "AuraFactory", "version": "6.0"}
