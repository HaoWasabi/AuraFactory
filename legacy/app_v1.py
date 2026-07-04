# app.py
"""
AuraFactory — Entry Point (Well-Architected Edition)

Đây là file chính kết nối tất cả components:
- Discord Bot (nextcord)
- LLM Provider (Gemini Phase 1, Bedrock Phase 2)
- Agent System (Orchestrator → Specialists)
- Observability (Tracing)
- Permission System (Risk-based approval)

Chạy: python app.py
"""
import os
import json
import asyncio
import nextcord
from nextcord.ext import commands
from nextcord.message import Message
from dotenv import load_dotenv

# Well-Architected components
from providers.gemini_provider import GeminiProvider
from agents.orchestrator import OrchestratorAgent
from agents.architect_agent import ArchitectAgent
from agents.copilot_agent import CopilotAgent
from observability.tracer import Tracer
from schemas.contracts import TaskStatus

load_dotenv()

# ============================================================
# CONFIG — Phase 1: Open-source/Free
# Phase 2: Đổi provider + config, KHÔNG đổi logic
# ============================================================

CONFIG = {
    "provider": "gemini",          # "gemini" | "bedrock" (Phase 2)
    "model": "gemini-2.5-flash",   # Phase 2: "anthropic.claude-3-5-sonnet-20241022-v2:0"
    "discord_token": os.getenv("DISCORD_TOKEN"),
    "llm_api_key": os.getenv("GEMINI_TOKEN"),
    "log_traces": True,
}

# ============================================================
# INITIALIZATION
# ============================================================

# 1. Observability (Principle 2: Observable)
tracer = Tracer(log_dir="logs/traces", console_output=True)

# 2. LLM Provider (Evolutionary Architecture: swap dễ dàng)
llm = GeminiProvider(api_key=CONFIG["llm_api_key"], model_id=CONFIG["model"])

# 3. Agents (Principle 1: Decomposed, bounded)
orchestrator = OrchestratorAgent(llm=llm, tracer=tracer)
architect = ArchitectAgent(llm=llm, tracer=tracer)
copilot = CopilotAgent(llm=llm, tracer=tracer)

# 4. Register specialists vào orchestrator
orchestrator.register_agent("architect", architect)
orchestrator.register_agent("copilot", copilot)
# orchestrator.register_agent("moderator", moderator)  # TODO
# orchestrator.register_agent("devops", devops)        # TODO

# ============================================================
# DISCORD BOT
# ============================================================

intents = nextcord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"""
╔══════════════════════════════════════════════════╗
║  🤖 AuraFactory v2.0 — Well-Architected Edition  ║
╠══════════════════════════════════════════════════╣
║  Bot: {bot.user.name:<41} ║
║  Provider: {CONFIG['provider']:<36} ║
║  Model: {CONFIG['model']:<39} ║
║  Agents: orchestrator, architect, copilot      ║
║  Tracing: {'ON' if CONFIG['log_traces'] else 'OFF':<39} ║
╚══════════════════════════════════════════════════╝
""")


@bot.event
async def on_message(message: Message):
    # Bỏ qua message của bot
    if message.author == bot.user:
        return
    if bot.user is None:
        return

    # Bot được mention → xử lý qua Agent System
    if bot.user in message.mentions:
        # Lấy prompt (xóa mention)
        prompt = message.content.replace(f'<@{bot.user.id}>', '').replace(f'<@!{bot.user.id}>', '').strip()
        
        if not prompt:
            await message.reply("Tag mình kèm nội dung yêu cầu nhé! 💡")
            return
        
        # Processing indicator
        processing_msg = await message.channel.send("🧠 Đang phân tích yêu cầu...")
        
        try:
            # === CORE: Agent System xử lý ===
            trace_id = tracer.new_trace()
            
            print(f"\n{'='*60}")
            print(f"📨 New Request [trace: {trace_id}]")
            print(f"   User: {message.author.name}")
            print(f"   Message: {prompt[:100]}...")
            print(f"{'='*60}")
            
            # Orchestrator decompose + route + execute
            result = await orchestrator.process_request(
                user_message=prompt,
                trace_id=trace_id,
                guild=message.guild,
            )
            
            # Format response cho Discord
            response_text = _format_response(result)
            
            # Xóa processing message
            await processing_msg.delete()
            
            # Gửi response (chia nhỏ nếu dài)
            chunks = [response_text[i:i+2000] for i in range(0, len(response_text), 2000)]
            for chunk in chunks:
                await message.reply(chunk)
            
            print(f"\n✅ Request completed [trace: {trace_id}]")
            
        except Exception as e:
            await processing_msg.delete()
            tracer.log_error(trace_id if 'trace_id' in dir() else "unknown", "system", str(e))
            await message.reply(f"❌ Lỗi: {str(e)[:500]}")
    
    # Cho phép commands (cogs) vẫn hoạt động
    await bot.process_commands(message)


def _format_response(result: dict) -> str:
    """Format agent result thành Discord message đẹp"""
    status = result.get("status", "unknown")
    
    if status == "clarification_needed":
        return f"❓ {result.get('message', 'Cần thêm thông tin')}"
    
    if status == "completed":
        lines = [f"📋 **Kế hoạch:** {result.get('plan', 'N/A')}\n"]
        
        for r in result.get("results", []):
            task_status = r.get("status", "unknown")
            icon = {"success": "✅", "failed": "❌", "needs_approval": "⚠️"}.get(task_status, "❓")
            
            if task_status == "needs_approval":
                lines.append(f"{icon} **Cần phê duyệt:** {r.get('error_message', '')}")
            elif task_status == "success":
                output = r.get("output", {})
                action = output.get("action", r.get("agent", ""))
                lines.append(f"{icon} **{action}** — Thành công")
                # Thêm chi tiết nếu có
                if "channel_name" in output:
                    lines.append(f"   → Channel: `{output['channel_name']}`")
            else:
                lines.append(f"{icon} Lỗi: {r.get('error_message', 'Unknown error')}")
        
        lines.append(f"\n🔍 *Trace ID: `{result.get('trace_id', 'N/A')}`*")
        return "\n".join(lines)
    
    return f"⚙️ Status: {status}\n{json.dumps(result, ensure_ascii=False, indent=2)[:1500]}"


# ============================================================
# LOAD EXISTING COGS (backward compatible)
# ============================================================

def load_cogs():
    """Load cogs cũ (commands/) — giữ backward compatibility"""
    for filename in os.listdir("commands"):
        if filename.endswith(".py") and filename != "__init__.py":
            cog_name = f"commands.{filename[:-3]}"
            try:
                bot.load_extension(cog_name)
                print(f"  ✅ Cog '{cog_name}' loaded")
            except Exception as e:
                print(f"  ⚠️ Cog '{cog_name}' failed: {e}")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print("🚀 Starting AuraFactory (Well-Architected Edition)...")
    print(f"   Provider: {CONFIG['provider']}")
    print(f"   Model: {CONFIG['model']}")
    print()
    
    load_cogs()
    bot.run(CONFIG["discord_token"])
