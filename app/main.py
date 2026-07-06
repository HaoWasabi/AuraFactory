# app/main.py
"""
AuraFactory — Main Entrypoint (v4.0)
7-Layer Architecture + 3-Mode Bot Lifecycle.
FastAPI + Discord Bot co-running.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from app.config import settings
logger = logging.getLogger(__name__)


# ============================================================
# DI CONTAINER
# ============================================================

class Container:
    """Dependency injection container."""
    llm = None
    db = None
    tracer = None
    metrics = None
    cost_tracker = None
    memory = None
    gateway = None
    mcp_client = None
    orchestrator = None
    admin_agent = None
    assistant_agent = None
    discord_adapter = None
    api_adapter = None
    knowledge_store = None
    server_crawler = None
    skill_registry = None


container = Container()


# ============================================================
# LIFESPAN
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    print("🚀 AuraFactory v4.0 starting...")

    # === Layer 7: Infrastructure ===
    from app.infra.llm import get_provider
    from app.infra.observability import Tracer, metrics
    from app.infra.database import DatabasePool
    from app.infra.cache import InMemoryCache

    container.tracer = Tracer(log_dir=settings.trace_log_dir, console_output=True)
    container.metrics = metrics

    # LLM Provider
    try:
        container.llm = get_provider()
        print(f"🧠 LLM Provider: {container.llm.model_name}")
    except RuntimeError as e:
        print(f"⚠️ {e}")
        print("⚠️ Starting without LLM — configure a provider in .env")

    # Database
    try:
        container.db = await DatabasePool.create(settings.database_url)
        print("✅ Database connected")
    except Exception as e:
        print(f"⚠️ Database not available: {e} — running without persistence")
        container.db = None

    cache = InMemoryCache()

    # === Layer 6: Memory + Knowledge ===
    from app.memory import MemoryService
    from app.knowledge.store import ServerKnowledgeStore
    from app.knowledge.crawler import ServerCrawler

    container.memory = MemoryService(
        vectorstore=None, db=container.db, cache=cache, embedding=None,
    )
    container.knowledge_store = ServerKnowledgeStore()
    container.server_crawler = ServerCrawler()
    print("📚 Knowledge Store initialized")

    # === MCP Layer ===
    from app.mcp import MCPClient
    from app.mcp.servers import DiscordMCPServer, MemoryMCPServer

    container.mcp_client = MCPClient()

    memory_server = MemoryMCPServer(memory_service=container.memory)
    container.mcp_client.register_server(memory_server)
    print(f"🔧 MCP: Memory server ({memory_server.info.tool_count} tools)")

    # === Layer 2: Gateway ===
    from app.gateway.pipeline import GatewayPipeline
    from app.gateway.session_manager import SessionManager
    from app.gateway.rate_limiter import RateLimiter
    from app.gateway.cost_tracker import cost_tracker

    container.cost_tracker = cost_tracker
    container.gateway = GatewayPipeline(
        rate_limiter=RateLimiter(),
        session_manager=SessionManager(),
        tracer=container.tracer,
    )

    # === Layer 3: Agents ===
    if container.llm:
        from app.agents import OrchestratorAgent, AdminAgent, AssistantAgent, ArchitectAgent

        # Create agents
        container.assistant_agent = AssistantAgent(
            llm=container.llm,
            tracer=container.tracer,
            knowledge_store=container.knowledge_store,
            memory=container.memory,
        )

        container.admin_agent = AdminAgent(
            llm=container.llm,
            tracer=container.tracer,
            knowledge_store=container.knowledge_store,
        )
        container.admin_agent.set_mcp_client(container.mcp_client)
        container.admin_agent.set_memory(container.memory)

        # Architect specialist (delegate for complex multi-step ops)
        architect = ArchitectAgent(llm=container.llm, tracer=container.tracer)
        architect.set_mcp_client(container.mcp_client)
        container.admin_agent.register_specialist("architect", architect)

        # Orchestrator (thin router)
        container.orchestrator = OrchestratorAgent(
            llm=container.llm,
            tracer=container.tracer,
            knowledge_store=container.knowledge_store,
            memory=container.memory,
        )
        container.orchestrator.set_admin_agent(container.admin_agent)
        container.orchestrator.set_assistant_agent(container.assistant_agent)

        print("🤖 Agents: orchestrator → admin_agent, assistant_agent, architect")

    # === Layer 1: Channels ===
    from app.channels.discord_adapter import DiscordAdapter
    from app.channels.api_adapter import api_adapter

    container.api_adapter = api_adapter

    if settings.discord_token:
        container.discord_adapter = DiscordAdapter(
            token=settings.discord_token,
            allowed_guild_ids=settings.allowed_guild_ids,
            allow_all=settings.allow_all_guilds,
        )
        container.discord_adapter.set_handler(_handle_message)
        container.discord_adapter.set_guild_join_handler(_handle_guild_join)
        container.discord_adapter.set_member_join_handler(_handle_member_join)
        container.discord_adapter.set_server_change_handler(_handle_server_change)

        # Discord MCP Server
        discord_mcp = DiscordMCPServer(bot=container.discord_adapter._bot)
        container.mcp_client.register_server(discord_mcp)
        print(f"🔧 MCP: Discord server ({discord_mcp.info.tool_count} tools)")

        # Reload Skills Registry with Discord tools now available
        from app.skills.startup import init_skills
        container.skill_registry = init_skills(
            mcp_client=container.mcp_client,
            skills_dir="./skills",
        )
        print(f"📋 Skills Registry: {container.skill_registry.tool_count} tools loaded")

        # Wire SkillRegistry + Validator into AdminAgent
        if container.admin_agent:
            from app.skills.startup import get_validator
            container.admin_agent.set_skill_registry(
                container.skill_registry, get_validator()
            )

        asyncio.create_task(container.discord_adapter.start())
        print(f"🤖 Discord bot starting... | MCP total: {container.mcp_client.tool_count} tools")
    else:
        print("⚠️ DISCORD_TOKEN missing — bot won't connect")

    # === Layer 4: Skills Registry (fallback if no Discord) ===
    if container.skill_registry is None:
        from app.skills.startup import init_skills
        container.skill_registry = init_skills(
            mcp_client=container.mcp_client,
            skills_dir="./skills",
        )
        print(f"📋 Skills Registry: {container.skill_registry.tool_count} tools loaded")
        # Wire SkillRegistry into AdminAgent (no Discord case)
        if container.admin_agent:
            from app.skills.startup import get_validator
            container.admin_agent.set_skill_registry(
                container.skill_registry, get_validator()
            )

    container.api_adapter.set_handler(_handle_message)
    print("✅ All systems ready")
    yield

    # === Shutdown ===
    if container.discord_adapter:
        await container.discord_adapter.stop()
    if container.db:
        await container.db.close()
    print("👋 AuraFactory shutdown")


# ============================================================
# MESSAGE HANDLER
# ============================================================

async def _handle_message(incoming) -> "OutgoingMessage":
    """Gateway → Orchestrator → Response."""
    from app.models.messages import OutgoingMessage

    result = await container.gateway.process(incoming)

    if not result.allowed:
        return OutgoingMessage(
            content=result.rejection_reason,
            trace_id=result.context.trace_id if result.context else "",
            source=incoming.source,
        )

    if container.orchestrator:
        response = await container.orchestrator.handle(
            prompt=incoming.prompt,
            user_id=incoming.user_id,
            guild_id=incoming.guild_id,
            context=result.context,
        )
        return OutgoingMessage(
            content=response.get("content", ""),
            trace_id=result.context.trace_id,
            source=incoming.source,
        )
    else:
        return OutgoingMessage(
            content="⚠️ Hệ thống chưa sẵn sàng (thiếu LLM provider).",
            trace_id=result.context.trace_id if result.context else "",
            source=incoming.source,
        )


# ============================================================
# LIFECYCLE EVENT HANDLERS
# ============================================================

async def _handle_guild_join(guild) -> None:
    """Bot added to new server → crawl → DM admin with setup greeting."""
    logger.info(f"Guild join: {guild.name} ({guild.id})")

    knowledge = await container.server_crawler.crawl(guild)
    await container.knowledge_store.save(knowledge)

    owner = guild.owner
    if owner:
        greeting = (
            f"👋 Chào! Tôi là **AuraFactory** — AI assistant cho server **{guild.name}**.\n\n"
            f"Server hiện có **{len(guild.channels)} channels** và **{guild.member_count} members**.\n\n"
            f"Bạn muốn tôi giúp gì?\n"
            f"1️⃣ **Setup server** — tạo channels, roles theo mô tả\n"
            f"2️⃣ **Hỗ trợ member** — auto chào đón, trả lời Q&A\n"
            f"3️⃣ **Cả hai**\n\n"
            f"_(Mô tả server của bạn để tôi đề xuất structure nhé!)_"
        )
        await container.discord_adapter.send_dm(owner.id, greeting)


async def _handle_member_join(member) -> None:
    """New member → generate + send onboarding DM."""
    guild = member.guild

    if not await container.knowledge_store.is_setup_complete(guild.id):
        return

    if container.assistant_agent:
        try:
            welcome = await container.assistant_agent.generate_onboarding(
                guild_id=guild.id, member_name=member.display_name,
            )
            await container.discord_adapter.send_dm(member.id, welcome)
        except Exception as e:
            logger.error(f"Onboarding DM failed: {e}")


async def _handle_server_change(guild, event_type: str) -> None:
    """Server structure changed → incremental knowledge update."""
    knowledge = await container.knowledge_store.load(guild.id)
    if knowledge:
        updated = await container.server_crawler.incremental_update(knowledge, guild, event_type)
        await container.knowledge_store.save(updated)


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="AuraFactory API",
    version="4.0.0",
    description="Agentic AI Discord Bot — 3-Mode Lifecycle",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.channels.api_adapter import router as api_router
app.include_router(api_router)


@app.get("/", tags=["system"])
async def root():
    """Root endpoint — for health checks and quick status."""
    return JSONResponse(content={"status": "ok", "service": "AuraFactory"})


@app.get("/health", tags=["system"])
async def health():
    return {"status": "healthy", "version": "4.0.0"}


@app.get("/metrics", tags=["observability"])
async def get_metrics():
    return JSONResponse(content=container.metrics.get_summary() if container.metrics else {})


@app.get("/knowledge/{guild_id}", tags=["knowledge"])
async def get_guild_knowledge(guild_id: int):
    knowledge = await container.knowledge_store.load(guild_id)
    if knowledge:
        return JSONResponse(content={
            "guild_name": knowledge.guild_name,
            "channels": len(knowledge.channels),
            "roles": len(knowledge.roles),
            "setup_complete": knowledge.setup_complete,
        })
    return JSONResponse(content={"error": "No knowledge found"}, status_code=404)


@app.get("/mcp/status", tags=["system"])
async def get_mcp_status():
    if container.mcp_client:
        return JSONResponse(content={
            "total_tools": container.mcp_client.tool_count,
            "tool_names": container.mcp_client.list_tool_names(),
        })
    return JSONResponse(content={"status": "not initialized"})


@app.get("/skills", tags=["system"])
async def get_skills_status():
    """Get Skills Registry summary."""
    if container.skill_registry:
        summary = container.skill_registry.get_tool_summary()
        return JSONResponse(content=summary)
    return JSONResponse(content={"status": "not initialized"})


@app.get("/skills/{agent_role}", tags=["system"])
async def get_skills_for_agent(agent_role: str):
    """Get tools available to a specific agent role."""
    if container.skill_registry:
        from app.agents.contracts import AgentRole
        try:
            role = AgentRole(agent_role)
            tools = container.skill_registry.get_planning_context(role)
            return JSONResponse(content={"agent": agent_role, "tools": tools, "count": len(tools)})
        except ValueError:
            return JSONResponse(content={"error": f"Unknown role: {agent_role}"}, status_code=400)
    return JSONResponse(content={"status": "not initialized"})


# ============================================================
if __name__ == "__main__":
    import uvicorn
    print("""
╔══════════════════════════════════════════════════════╗
║  🚀 AuraFactory v4.0 — 3-Mode Bot                  ║
╠══════════════════════════════════════════════════════╣
║  Orchestrator → AdminAgent | AssistantAgent         ║
║  API: http://localhost:8000/docs                    ║
╚══════════════════════════════════════════════════════╝
""")
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.debug)
