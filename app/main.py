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

    # === L2: Infrastructure ===
    from app.database import Database
    db = Database()
    db_connected = False
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

    from app.llm import get_llm, get_bedrock_llm, LLMRouter, GeminiLLM
    llm = None
    llm_planner = None    # Planner: needs smartest model (Nova Pro)
    llm_classifier = None  # Classifier: can use lightest model (Nova Micro)
    try:
        # --- Build Gemini fallback provider (nếu cần) ---
        gemini_fallback = None
        if settings.LLM_FALLBACK_ENABLED:
            if settings.GEMINI_API_KEY:
                # Thử model ưu tiên, fallback về gemini-2.0-flash nếu lỗi
                preferred_model = settings.GEMINI_FALLBACK_MODEL  # mặc định gemini-2.0-flash
                try:
                    gemini_fallback = GeminiLLM(model=preferred_model, api_key=settings.GEMINI_API_KEY)
                    logger.info("✅ Gemini fallback provider: model=%s (nguồn: %s)",
                                preferred_model,
                                "env GEMINI_FALLBACK_MODEL" if preferred_model != 'gemini-2.5-flash' else "default")
                except Exception as fe:
                    logger.warning("⚠️ Gemini fallback model '%s' thất bại (%s) — thử gemini-2.0-flash", preferred_model, fe)
                    try:
                        gemini_fallback = GeminiLLM(model='gemini-2.0-flash', api_key=settings.GEMINI_API_KEY)
                        logger.info("✅ Gemini fallback provider: model=gemini-2.0-flash (fallback)")
                    except Exception as fe2:
                        logger.error("❌ Toàn bộ chuỗi fallback model thất bại: %s", fe2)
                        gemini_fallback = None
            else:
                logger.warning("⚠️ LLM_FALLBACK_ENABLED=true nhưng GEMINI_API_KEY chưa thiết lập — fallback bị tắt")

        # --- Build primary provider ---
        def _wrap_router(primary, fallback_for_this=None):
            """Bọc provider trong LLMRouter."""
            return LLMRouter(
                primary=primary,
                fallback=fallback_for_this or gemini_fallback,
                fallback_enabled=settings.LLM_FALLBACK_ENABLED,
            )

        if settings.LLM_PROVIDER == "bedrock":
            # Default model (Classifier fallback, Query, ReAct, Executor)
            _llm_raw = get_bedrock_llm(model=settings.BEDROCK_MODEL_ID, region=settings.AWS_REGION)
            llm = _wrap_router(_llm_raw)

            # Planner uses a heavier model for complex JSON plan generation
            if settings.BEDROCK_PLANNER_MODEL != settings.BEDROCK_MODEL_ID:
                _planner_raw = get_bedrock_llm(model=settings.BEDROCK_PLANNER_MODEL, region=settings.AWS_REGION)
                llm_planner = _wrap_router(_planner_raw)
            else:
                llm_planner = llm

            # Classifier uses the lightest/cheapest model (Nova Micro by default)
            if settings.BEDROCK_CLASSIFIER_MODEL != settings.BEDROCK_MODEL_ID:
                _cls_raw = get_bedrock_llm(model=settings.BEDROCK_CLASSIFIER_MODEL, region=settings.AWS_REGION)
                llm_classifier = _wrap_router(_cls_raw)
            else:
                llm_classifier = llm

            logger.info(
                "✅ Bedrock multi-model routing: default=%s planner=%s classifier=%s region=%s fallback=%s",
                settings.BEDROCK_MODEL_ID,
                settings.BEDROCK_PLANNER_MODEL,
                settings.BEDROCK_CLASSIFIER_MODEL,
                settings.AWS_REGION,
                "enabled" if settings.LLM_FALLBACK_ENABLED else "disabled",
            )
        else:
            _gemini_raw = get_llm(
                provider=settings.LLM_PROVIDER,
                model=settings.GEMINI_MODEL,
                api_key=settings.GEMINI_API_KEY,
            )
            llm = _wrap_router(_gemini_raw, fallback_for_this=None)  # Gemini không fallback về Gemini
            llm_planner = llm
            llm_classifier = llm
            logger.info(
                "✅ LLM provider: %s (%s) fallback=%s",
                settings.LLM_PROVIDER, settings.GEMINI_MODEL,
                "disabled (primary đã là Gemini)" if settings.LLM_PROVIDER == "gemini" else "disabled",
            )

        # Expose llm_router cho API endpoints
        app.state.llm_router = llm  # router chính (dùng để switch provider / update key)

    except Exception as e:
        logger.error("❌ LLM initialization FAILED: %s", e, exc_info=True)
        logger.error("   AI features (classify, plan, query) will NOT work.")

    # === L4: MCP ===
    from app.mcp import MCPClient
    from app.mcp.servers.discord_server import DiscordMCPServer

    mcp_client = MCPClient()
    discord_mcp_server = DiscordMCPServer()
    # Note: bot reference set later in on_ready
    mcp_client.register_server(discord_mcp_server)
    logger.info("✅ MCP client ready (discord server registered, awaiting bot)")

    # === L6: Services ===
    from app.services.rate_limit_service import RateLimitService
    from app.services.request_service import RequestService
    from app.services.classifier_service import ClassifierService
    from app.services.context_service import ContextService
    from app.services.planner_service import PlannerService
    from app.services.approval_service import ApprovalService
    from app.services.executor_service import ExecutorService
    from app.services.query_service import QueryService
    from app.services.auth_service import AuthService
    from app.services.guild_sync_service import GuildSyncService
    from app.services.session_service import SessionService

    rate_limit_service = RateLimitService(db)
    request_service = RequestService(db, rate_limit_service=rate_limit_service)
    classifier_service = ClassifierService(llm_classifier)
    context_service = ContextService(db, mcp_client)
    planner_service = PlannerService(db, llm_planner, mcp_client, context_service)
    approval_service = ApprovalService(db)
    executor_service = ExecutorService(db, mcp_client, llm, context_service)
    query_service = QueryService(llm, mcp_client, context_service)
    auth_service = AuthService(db)
    guild_sync_service = GuildSyncService(db)
    session_service = SessionService(db)

    services = {
        "rate_limit_service": rate_limit_service,
        "request_service": request_service,
        "classifier_service": classifier_service,
        "context_service": context_service,
        "planner_service": planner_service,
        "approval_service": approval_service,
        "executor_service": executor_service,
        "query_service": query_service,
        "auth_service": auth_service,
        "guild_sync_service": guild_sync_service,
        "session_service": session_service,
        "_mcp_client": mcp_client,
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
    if not hasattr(app.state, 'llm_router') or app.state.llm_router is None:
        app.state.llm_router = llm  # fallback nếu llm_router chưa được set trong try block

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
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Static files + Page routes ===
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")


@app.get("/")
async def serve_index():
    return FileResponse("frontend/index.html")

@app.head("/")
async def head_index():
    """Health check probe (Render sends HEAD /)."""
    return Response(status_code=200)


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
