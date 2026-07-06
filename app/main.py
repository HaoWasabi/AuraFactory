# app/main.py
"""
AuraFactory — Main Entrypoint.
FastAPI application with lifespan managing all services.
DI container pattern via app.state.

Architecture:
  Channel (Discord/API/Web) → Gateway → Orchestrator → Agent → MCP Tools → Response
"""
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import settings

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ================================================================
# Lifespan — Startup & Shutdown
# ================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — initialize and teardown all services."""
    logger.info("🚀 AuraFactory starting up...")
    start_time = time.time()

    # Store start time
    app.state.start_time = start_time

    # Session store (in-memory, signed cookies for validation)
    app.state.session_store = {}

    # Approval store (in-memory HITL queue)
    app.state.approval_store = {}

    # === Infrastructure Services ===
    try:
        # Database
        from app.infra.database import DatabasePool
        db = DatabasePool(settings.database_url)
        await db.connect()
        app.state.db = db
        logger.info("✅ Database connected")
    except Exception as e:
        logger.warning(f"⚠️ Database unavailable (running without): {e}")
        app.state.db = None

    # LLM Router
    from app.infra.llm import get_provider, ModelRouter
    try:
        primary_provider = get_provider(settings.llm_provider)
        llm_router = ModelRouter(primary=primary_provider)
        app.state.llm_router = llm_router
        app.state.llm = primary_provider
        logger.info(f"✅ LLM provider: {settings.llm_provider}")
    except Exception as e:
        logger.error(f"❌ LLM initialization failed: {e}")
        raise RuntimeError(f"Cannot start without LLM: {e}")

    # Cache
    from app.infra.cache import InMemoryCache
    cache = InMemoryCache()
    app.state.cache = cache
    logger.info("✅ Cache initialized (in-memory)")

    # Observability
    from app.infra.observability import Tracer, metrics
    tracer = Tracer(log_dir=settings.trace_log_dir)
    app.state.tracer = tracer
    app.state.metrics = metrics
    logger.info("✅ Tracer initialized")

    # === Knowledge & Memory ===
    from app.knowledge import ServerKnowledgeStore, ServerCrawler
    knowledge_store = ServerKnowledgeStore()
    app.state.knowledge_store = knowledge_store
    logger.info("✅ Knowledge store ready")

    from app.memory import MemoryService
    memory_service = MemoryService()
    app.state.memory = memory_service
    logger.info("✅ Memory service ready")

    # === Skills & MCP ===
    from app.skills import SkillRegistry
    skill_registry = SkillRegistry()
    await skill_registry.init_skills()
    app.state.skill_registry = skill_registry
    logger.info(f"✅ Skills loaded: {skill_registry.count()} skills")

    from app.mcp import MCPClient
    mcp_client = MCPClient()
    app.state.mcp_client = mcp_client

    # Register MCP servers (Discord tools, etc.)
    try:
        from app.mcp.servers import register_all_servers
        await register_all_servers(mcp_client)
        logger.info(f"✅ MCP servers registered: {len(mcp_client._servers)} servers")
    except ImportError:
        logger.warning("⚠️ MCP servers module not found — running without tool servers")
    except Exception as e:
        logger.warning(f"⚠️ MCP server registration partial: {e}")

    # === Gateway Pipeline ===
    from app.gateway import GatewayPipeline
    from app.gateway.rate_limiter import RateLimiter
    from app.gateway.session_manager import SessionManager

    gateway = GatewayPipeline(
        rate_limiter=RateLimiter(),
        session_manager=SessionManager(),
        tracer=tracer,
    )
    app.state.gateway = gateway
    logger.info("✅ Gateway pipeline ready")

    # === Agents ===
    from app.agents import OrchestratorAgent, AdminAgent, AssistantAgent, ArchitectAgent
    from app.agents.fast_track import FastTrackExecutor

    orchestrator = OrchestratorAgent(
        llm=primary_provider,
        tracer=tracer,
        knowledge_store=knowledge_store,
        memory=memory_service,
    )

    admin_agent = AdminAgent(
        llm=primary_provider,
        mcp_client=mcp_client,
        tracer=tracer,
        knowledge_store=knowledge_store,
        approval_store=app.state.approval_store,
    )

    assistant_agent = AssistantAgent(
        llm=primary_provider,
        knowledge_store=knowledge_store,
        memory=memory_service,
        tracer=tracer,
    )

    architect_agent = ArchitectAgent(
        llm=primary_provider,
        mcp_client=mcp_client,
        tracer=tracer,
    )

    fast_track = FastTrackExecutor(
        llm=primary_provider,
        mcp_client=mcp_client,
        tracer=tracer,
    )

    # Wire agents
    orchestrator.set_admin_agent(admin_agent)
    orchestrator.set_assistant_agent(assistant_agent)
    orchestrator.set_fast_track(fast_track)
    admin_agent.set_architect(architect_agent)

    app.state.orchestrator = orchestrator
    app.state.admin_agent = admin_agent
    app.state.assistant_agent = assistant_agent
    app.state.architect_agent = architect_agent
    app.state.fast_track = fast_track
    logger.info("✅ All agents initialized and wired")

    # === Process Message Function (DI entry point) ===
    from app.models.messages import IncomingMessage, OutgoingMessage

    async def process_message(msg: IncomingMessage) -> OutgoingMessage:
        """Central message processing — Gateway → Orchestrator → Response."""
        # Run through gateway
        gateway_result = await gateway.process(msg)

        if not gateway_result.allowed:
            return OutgoingMessage(
                content=gateway_result.rejection_reason,
                trace_id="rejected",
                target_channel_id=msg.channel_id,
                source=msg.source,
            )

        # Route to orchestrator
        result = await orchestrator.handle(
            prompt=gateway_result.message.prompt,
            user_id=msg.user_id,
            guild_id=msg.guild_id,
            trace_id=gateway_result.context.trace_id,
            session_id=gateway_result.context.session_id,
            context=gateway_result.context,
        )

        return OutgoingMessage(
            content=result.get("content", "Không thể xử lý yêu cầu."),
            trace_id=gateway_result.context.trace_id,
            target_channel_id=msg.channel_id,
            source=msg.source,
            metadata=result,
        )

    app.state.process_message = process_message

    # === Discord Bot (background task) ===
    from app.channels.discord_adapter import DiscordAdapter

    crawler = ServerCrawler(knowledge_store=knowledge_store)

    discord_adapter = DiscordAdapter(
        token=settings.discord_token,
        process_message_fn=process_message,
        knowledge_crawler=crawler,
    )
    app.state.discord_adapter = discord_adapter

    # Start bot in background (non-blocking)
    bot_task = None
    if settings.discord_token:
        bot_task = asyncio.create_task(_start_bot(discord_adapter))
        logger.info("🤖 Discord bot starting in background...")
    else:
        logger.warning("⚠️ No DISCORD_TOKEN — bot will not connect")

    # === Include Routers ===
    from app.channels.api_adapter import router as api_router
    from app.channels.web_routes import router as web_router

    app.include_router(api_router)
    app.include_router(web_router)

    # === Startup Complete ===
    elapsed = time.time() - start_time
    logger.info(f"✅ AuraFactory ready in {elapsed:.2f}s")

    yield  # Application is running

    # === Shutdown ===
    logger.info("🛑 AuraFactory shutting down...")

    # Stop Discord bot
    if discord_adapter:
        await discord_adapter.stop()

    # Cancel bot task
    if bot_task and not bot_task.done():
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass

    # Disconnect database
    if app.state.db:
        await app.state.db.disconnect()

    logger.info("👋 AuraFactory stopped.")


async def _start_bot(adapter: "DiscordAdapter") -> None:
    """Start Discord bot — handles reconnection."""
    try:
        await adapter.start()
    except Exception as e:
        logger.error(f"Discord bot error: {e}", exc_info=True)


# ================================================================
# FastAPI Application
# ================================================================

app = FastAPI(
    title="AuraFactory",
    description="AI-powered Discord server management system",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
static_path = Path("frontend/static")
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")


# ================================================================
# Root Health Endpoints (for Render)
# ================================================================

@app.head("/")
async def head_root():
    """HEAD / — Render health check."""
    return PlainTextResponse("OK")


@app.get("/ping")
async def ping():
    """Simple ping endpoint."""
    return {"ping": "pong"}


# ================================================================
# Global Error Handlers
# ================================================================

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """Custom 404 handler."""
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=404,
            content={"error": "Not found", "path": request.url.path},
        )
    return JSONResponse(
        status_code=404,
        content={"error": "Không tìm thấy trang."},
    )


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    """Custom 500 handler."""
    logger.error(f"Internal error on {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Lỗi hệ thống. Vui lòng thử lại sau."},
    )


@app.exception_handler(429)
async def rate_limit_handler(request: Request, exc):
    """Rate limit exceeded."""
    return JSONResponse(
        status_code=429,
        content={"error": "Bạn đang gửi quá nhanh. Vui lòng đợi."},
    )
