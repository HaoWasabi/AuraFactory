# server.py
"""
AuraFactory API Server — Well-Architected Edition

Architecture:
  Frontend (HTML) → FastAPI → Orchestrator → Specialist Agents → Discord

Endpoints:
  POST /chat          — Gửi prompt, nhận kết quả
  GET  /health        — Health check
  GET  /approvals     — Xem pending approvals
  POST /approve/{id}  — Phê duyệt action
  POST /reject/{id}   — Từ chối action
  GET  /traces/{id}   — Xem trace chi tiết
  GET  /guilds        — Liệt kê guilds

Chạy: python server.py
"""
import os
import json
import asyncio
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# Well-Architected components
from providers.gemini_provider import GeminiProvider
from agents.orchestrator import OrchestratorAgent
from agents.architect_agent import ArchitectAgent
from agents.copilot_agent import CopilotAgent
from observability.tracer import Tracer
from schemas.approval import ApprovalStore
from schemas.permissions import get_risk_level

# ============================================================
# INITIALIZATION
# ============================================================

tracer = Tracer(log_dir="logs/traces", console_output=True)
approval_store = ApprovalStore()

# LLM Provider (Phase 1: Gemini)
llm = GeminiProvider(
    api_key=os.getenv("GEMINI_TOKEN"),
    model_id=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
)

# Agent System
orchestrator = OrchestratorAgent(llm=llm, tracer=tracer)
architect = ArchitectAgent(llm=llm, tracer=tracer)
copilot = CopilotAgent(llm=llm, tracer=tracer)

orchestrator.register_agent("architect", architect)
orchestrator.register_agent("copilot", copilot)

# Discord Bot (background)
import nextcord
from nextcord.ext import commands

intents = nextcord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

TARGET_GUILD_ID = int(os.getenv("GUILD_ID", "0"))

# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="AuraFactory API",
    version="2.0",
    description="Agentic AI Discord Management — Well-Architected Edition",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Request/Response Models ===

class ChatRequest(BaseModel):
    message: str
    guild_id: Optional[int] = None


class ChatResponse(BaseModel):
    status: str
    plan: str = ""
    results: list = []
    trace_id: str = ""
    message: str = ""
    pending_approvals: list = []


class ApprovalAction(BaseModel):
    approver: str = "admin"
    reason: str = ""


# ============================================================
# ENDPOINTS
# ============================================================

@app.get("/health")
async def health():
    """Health check — kiểm tra system status"""
    return {
        "status": "ok",
        "bot_connected": bot.is_ready(),
        "guild": bot.get_guild(TARGET_GUILD_ID).name if bot.is_ready() and bot.get_guild(TARGET_GUILD_ID) else None,
        "provider": llm.model_name,
        "agents": ["orchestrator", "architect", "copilot"],
        "pending_approvals": len(approval_store.list_pending()),
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Main endpoint — nhận prompt từ frontend, xử lý qua Agent System.
    Nếu action cần approval → trả pending_approvals để frontend hiện nút.
    """
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message không được trống")
    
    guild = None
    guild_id = request.guild_id or TARGET_GUILD_ID
    if bot.is_ready() and guild_id:
        guild = bot.get_guild(guild_id)
    
    trace_id = tracer.new_trace()
    
    print(f"\n{'='*60}")
    print(f"📨 Request [trace: {trace_id}]")
    print(f"   Message: {request.message[:100]}...")
    print(f"   Guild: {guild.name if guild else 'NOT CONNECTED'}")
    print(f"{'='*60}")
    
    try:
        result = await orchestrator.process_request(
            user_message=request.message,
            trace_id=trace_id,
            guild=guild,
        )
        
        # Check nếu có action cần approval → tạo pending
        pending = []
        for r in result.get("results", []):
            if r.get("status") == "needs_approval":
                output = r.get("output", {})
                approval = approval_store.create(
                    trace_id=trace_id,
                    agent_id=r.get("agent", "unknown"),
                    action=output.get("action", "unknown"),
                    parameters=output.get("parameters", {}),
                    risk_level=get_risk_level(output.get("action", "")).value,
                )
                pending.append(approval.to_dict())
        
        return ChatResponse(
            status=result.get("status", "unknown"),
            plan=result.get("plan", ""),
            results=result.get("results", []),
            trace_id=trace_id,
            message=_format_response(result),
            pending_approvals=pending,
        )
    
    except Exception as e:
        tracer.log_error(trace_id, "server", str(e))
        return ChatResponse(
            status="error",
            trace_id=trace_id,
            message=f"❌ Lỗi: {str(e)}",
        )


# === APPROVAL ENDPOINTS ===

@app.get("/approvals")
async def list_approvals():
    """Liệt kê tất cả pending approvals"""
    return {
        "pending": approval_store.list_pending(),
        "all": approval_store.list_all(),
    }


@app.post("/approve/{approval_id}")
async def approve_action(approval_id: str, body: ApprovalAction = ApprovalAction()):
    """
    Admin approve action → Agent execute.
    """
    approval = approval_store.approve(approval_id, approver=body.approver)
    
    if not approval:
        raise HTTPException(status_code=404, detail="Approval không tồn tại")
    
    if approval.status != "approved":
        return {"status": approval.status, "message": f"Đã {approval.status} trước đó"}
    
    # Execute action thật
    tracer.log_approval(
        approval.trace_id, approval.agent_id,
        action=approval.action, approved=True, approver=body.approver
    )
    
    # Lấy guild
    guild = bot.get_guild(TARGET_GUILD_ID) if bot.is_ready() else None
    
    if not guild:
        return {
            "status": "approved_but_not_executed",
            "message": "Đã approve nhưng bot chưa connect Discord",
            "approval": approval.to_dict(),
        }
    
    # Route tới đúng agent để execute
    from schemas.contracts import TaskAssignment, AgentRole
    
    task = TaskAssignment(
        task_id=f"{approval.trace_id}-approved",
        target_agent=AgentRole(approval.agent_id),
        action=approval.action,
        parameters=approval.parameters,
        priority="high",
        success_criteria=f"Execute {approval.action} after admin approval",
    )
    
    # Tìm đúng agent
    agent = orchestrator._specialists.get(approval.agent_id)
    if not agent:
        return {"status": "error", "message": f"Agent '{approval.agent_id}' not found"}
    
    # Execute với skip_approval=True (đã được human approve)
    result = await agent.execute_task(task, approval.trace_id, guild, skip_approval=True)
    
    return {
        "status": "executed",
        "message": f"✅ Action '{approval.action}' đã được thực hiện!",
        "result": result.to_dict(),
        "approval": approval.to_dict(),
    }


@app.post("/reject/{approval_id}")
async def reject_action(approval_id: str, body: ApprovalAction = ApprovalAction()):
    """Admin từ chối action"""
    approval = approval_store.reject(approval_id, approver=body.approver, reason=body.reason)
    
    if not approval:
        raise HTTPException(status_code=404, detail="Approval không tồn tại")
    
    tracer.log_approval(
        approval.trace_id, approval.agent_id,
        action=approval.action, approved=False, approver=body.approver
    )
    
    return {
        "status": "rejected",
        "message": f"❌ Action '{approval.action}' đã bị từ chối",
        "approval": approval.to_dict(),
    }


# === OBSERVABILITY ENDPOINTS ===

@app.get("/traces/{trace_id}")
async def get_trace(trace_id: str):
    """Xem trace chi tiết — debug + monitoring"""
    events = tracer.get_trace(trace_id)
    return {"trace_id": trace_id, "events": events, "count": len(events)}


@app.get("/guilds")
async def list_guilds():
    """Liệt kê guilds bot đang tham gia"""
    if not bot.is_ready():
        return {"guilds": [], "message": "Bot chưa connect Discord"}
    return {
        "guilds": [
            {"id": g.id, "name": g.name, "member_count": g.member_count}
            for g in bot.guilds
        ]
    }


# ============================================================
# HELPERS
# ============================================================

def _format_response(result: dict) -> str:
    """Format kết quả thành text cho frontend"""
    status = result.get("status", "unknown")
    
    if status == "clarification_needed":
        return result.get("message", "Cần thêm thông tin.")
    
    if status == "completed":
        lines = [f"📋 **Kế hoạch:** {result.get('plan', 'N/A')}\n"]
        
        for r in result.get("results", []):
            task_status = r.get("status", "unknown")
            icon = {
                "success": "✅",
                "failed": "❌",
                "needs_approval": "⚠️",
            }.get(task_status, "❓")
            
            if task_status == "needs_approval":
                lines.append(f"{icon} **Cần phê duyệt:** {r.get('error_message', '')}")
            elif task_status == "success":
                output = r.get("output", {})
                action = output.get("action", "")
                lines.append(f"{icon} **{action}** — Thành công")
                if "channel_name" in output:
                    lines.append(f"   → Channel: `{output['channel_name']}`")
                if "channel_id" in output:
                    lines.append(f"   → ID: `{output['channel_id']}`")
            else:
                lines.append(f"{icon} {r.get('error_message', 'Lỗi không xác định')}")
        
        return "\n".join(lines)
    
    return f"Status: {status}"


# ============================================================
# DISCORD BOT (Background)
# ============================================================

@bot.event
async def on_ready():
    print(f"\n🤖 Discord Bot connected: {bot.user.name}")
    print(f"   Guilds: {[g.name for g in bot.guilds]}")
    if TARGET_GUILD_ID:
        g = bot.get_guild(TARGET_GUILD_ID)
        print(f"   Target: {g.name if g else 'NOT FOUND'}")


@bot.event
async def on_message(message):
    """Bot respond khi được mention trên Discord — route qua Agent System"""
    if message.author == bot.user:
        return
    if bot.user is None:
        return
    
    if bot.user in message.mentions:
        prompt = message.content.replace(f'<@{bot.user.id}>', '').replace(f'<@!{bot.user.id}>', '').strip()
        
        if not prompt:
            await message.reply("Tag mình kèm nội dung yêu cầu nhé! 💡")
            return
        
        processing_msg = await message.channel.send("🧠 Đang xử lý...")
        
        try:
            trace_id = tracer.new_trace()
            result = await orchestrator.process_request(
                user_message=prompt,
                trace_id=trace_id,
                guild=message.guild,
            )
            
            response_text = _format_response(result)
            await processing_msg.delete()
            
            # Chia nhỏ nếu dài quá 2000 ký tự
            chunks = [response_text[i:i+2000] for i in range(0, len(response_text), 2000)]
            for chunk in chunks:
                await message.reply(chunk)
        
        except Exception as e:
            await processing_msg.delete()
            await message.reply(f"❌ Lỗi: {str(e)[:500]}")
    
    await bot.process_commands(message)


@app.on_event("startup")
async def startup_event():
    """Khởi động Discord bot song song với API"""
    token = os.getenv("DISCORD_TOKEN")
    if token:
        asyncio.create_task(bot.start(token))
        print("🚀 Discord bot starting...")
    else:
        print("⚠️ DISCORD_TOKEN missing — bot won't connect, chỉ có LLM planning")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    import uvicorn
    print("""
╔══════════════════════════════════════════════════════╗
║  🚀 AuraFactory API Server — Well-Architected       ║
╠══════════════════════════════════════════════════════╣
║  API:      http://localhost:8000                     ║
║  Docs:     http://localhost:8000/docs                ║
║  Health:   http://localhost:8000/health              ║
║  Provider: Gemini (Phase 1)                         ║
╚══════════════════════════════════════════════════════╝
""")
    uvicorn.run(app, host="0.0.0.0", port=8000)
