"""
AuraFactory — Main Entrypoint.
FastAPI application with lifespan managing all services.
7-layer architecture: Config → Infra → Models → MCP → Connectors → Services → Interfaces
"""
import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

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

    # === L2: Infrastructure ===
    from app.database import Database
    db = Database()
    db_connected = False
    for attempt in range(5):
        try:
            await db.connect()
            await db.run_migrations("migrations")
            logger.info("✅ Database connected + migrations applied")
            db_connected = True
            break
        except Exception as e:
            if attempt < 4:
                wait = 2 ** attempt  # 1, 2, 4, 8 seconds
                logger.warning("⚠️ DB connection attempt %d failed: %s — retrying in %ds...", attempt + 1, e, wait)
                await asyncio.sleep(wait)
            else:
                logger.error("❌ Database connection failed after 5 attempts: %s", e)
                raise RuntimeError(f"Cannot start without database: {e}")

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
        logger.warning("⚠️ LLM unavailable: %s", e)
        logger.warning("   Set GEMINI_API_KEY in .env to enable AI features.")

    # === L4: MCP ===
    from app.mcp import MCPClient
    from app.mcp.servers.discord_server import DiscordMCPServer

    mcp_client = MCPClient()
    discord_mcp_server = DiscordMCPServer()
    # Note: bot reference set later in on_ready
    mcp_client.register_server(discord_mcp_server)
    logger.info("✅ MCP client ready (discord server registered, awaiting bot)")

    # === L6: Services ===
    from app.services.request_service import RequestService
    from app.services.classifier_service import ClassifierService
    from app.services.context_service import ContextService
    from app.services.planner_service import PlannerService
    from app.services.approval_service import ApprovalService
    from app.services.executor_service import ExecutorService
    from app.services.query_service import QueryService
    from app.services.auth_service import AuthService
    from app.services.guild_sync_service import GuildSyncService

    request_service = RequestService(db)
    classifier_service = ClassifierService(llm)
    context_service = ContextService(db, mcp_client)
    planner_service = PlannerService(db, llm, mcp_client, context_service)
    approval_service = ApprovalService(db)
    executor_service = ExecutorService(db, mcp_client, llm, context_service)
    query_service = QueryService(llm, mcp_client, context_service)
    auth_service = AuthService(db)
    guild_sync_service = GuildSyncService(db)

    services = {
        "request_service": request_service,
        "classifier_service": classifier_service,
        "context_service": context_service,
        "planner_service": planner_service,
        "approval_service": approval_service,
        "executor_service": executor_service,
        "query_service": query_service,
        "auth_service": auth_service,
        "guild_sync_service": guild_sync_service,
    }
    logger.info("✅ All services initialized")

    # === L7: Interfaces ===
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
    version="5.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Static files + Page routes ===
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")


@app.get("/")
async def serve_index():
    return FileResponse("frontend/index.html")


@app.get("/login")
async def serve_login():
    return FileResponse("frontend/templates/login.html")


@app.get("/dashboard")
async def serve_dashboard():
    return FileResponse("frontend/templates/dashboard.html")


@app.get("/auth/callback")
async def serve_callback():
    return FileResponse("frontend/templates/callback.html")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "AuraFactory", "version": "5.0"}
