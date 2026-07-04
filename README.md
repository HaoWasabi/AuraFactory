# 🏭 AuraFactory

> **Agentic AI — Tự động hóa Discord Workspace**  
> Multi-Agent System với Human-in-the-Loop Approval

---

## 🏗️ Architecture

```
┌─────────────┐    HTTP    ┌─────────────────────────────────────┐
│  Frontend   │ ─────────→ │  server.py (FastAPI)                │
│  (Browser)  │ ←───────── │    ├── /chat                        │
└─────────────┘            │    ├── /approve/{id}                │
                           │    ├── /reject/{id}                 │
                           │    └── /health, /traces, /guilds    │
                           └─────────────┬───────────────────────┘
                                         │
                              ┌───────────▼───────────┐
                              │   OrchestratorAgent    │
                              │   (Plan & Route)       │
                              └───┬──────────────┬────┘
                                  │              │
                     ┌────────────▼──┐    ┌──────▼────────┐
                     │  Architect    │    │   Copilot     │
                     │  (Execute)    │    │   (Q&A)       │
                     └──────┬───────┘    └───────────────┘
                            │
                    ┌───────▼──────┐
                    │ Discord API  │ ← chỉ execute khi Human Approve
                    └──────────────┘
```

## 📁 Project Structure

```
AuraFactory/
├── server.py              ← 🚀 Entry point (FastAPI + Discord bot)
├── AFfrontend.html        ← Chat UI
├── requirements.txt
├── README.md
├── LICENSE
│
├── agents/                ← 🧠 Agent System
│   ├── base_agent.py         Permission check, retry, tracing
│   ├── orchestrator.py       Phân tích → route tasks
│   ├── architect_agent.py    Execute Discord operations
│   └── copilot_agent.py      Q&A, translate, events
│
├── prompts/               ← 💬 System Prompts (tách riêng, dễ edit)
│   ├── orchestrator.md
│   ├── architect.md
│   └── copilot.md
│
├── schemas/               ← 📋 Contracts + Rules
│   ├── contracts.py          TaskAssignment, TaskResult
│   ├── permissions.py        Risk levels, agent scope
│   └── approval.py           Human-in-the-loop store
│
├── providers/             ← 🔌 LLM Providers (pluggable)
│   ├── base.py               Abstract interface
│   └── gemini_provider.py    Google Gemini (Phase 1)
│
├── tools/                 ← 🔧 Discord API Wrappers
│   ├── discord_channel.py
│   ├── discord_category.py
│   ├── discord_role.py
│   ├── discord_member.py
│   ├── discord_guild.py
│   ├── discord_webhook.py
│   ├── discord_backup.py
│   └── discord_features.py
│
├── commands/              ← ⌨️ Discord Slash Commands
├── observability/         ← 📊 Tracing
│   └── tracer.py
├── config/                ← ⚙️ Settings
│   └── settings.py
├── docs/                  ← 📜 Legal
│   ├── privacy.md
│   └── terms.md
└── logs/                  ← 📁 Trace logs (auto-generated)
```

## 🚀 Quick Start

```bash
# 1. Install
pip install -r requirements.txt

# 2. Tạo file .env
DISCORD_TOKEN=your_bot_token
GUILD_ID=your_server_id
GEMINI_TOKEN=your_gemini_key

# 3. Chạy
python server.py

# 4. Sử dụng
#  → Mở AFfrontend.html trên browser (Chat UI)
#  → Hoặc mention bot trên Discord
#  → API docs: http://localhost:8000/docs
```

## 🛡️ Human-in-the-Loop Approval

| Action | Risk | Behavior |
|--------|------|----------|
| `create_channel` | 🟡 MEDIUM | Auto-execute |
| `delete_channel` | 🔴 HIGH | Block → cần Approve |
| `kick_member` | 🔴 HIGH | Block → cần Approve |
| `ban_member` | 🔴 CRITICAL | Block → cần Approve |

```
User: "Xóa kênh general"
  → Orchestrator plan → route Architect
  → HIGH risk detected → TẠM DỪNG
  → Frontend hiện [✅ Phê duyệt] [❌ Từ chối]
  → Admin click ✅ → Execute → Done
```

## 🧪 API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/chat` | Gửi prompt |
| GET | `/health` | System status |
| GET | `/approvals` | Pending approvals |
| POST | `/approve/{id}` | Phê duyệt |
| POST | `/reject/{id}` | Từ chối |
| GET | `/traces/{id}` | Trace chi tiết |
| GET | `/guilds` | Discord servers |

## 📐 Design Principles

Thiết kế theo **AWS Well-Architected Framework** + **Agentic AI Lens**:

| Principle | Implementation |
|-----------|---------------|
| Decompose | Mỗi agent 1 scope, 1 file |
| Observable | Mọi action traced (`observability/`) |
| Behavior as Code | Prompts tách file, versioned (`prompts/`) |
| Autonomy + Oversight | Risk levels + approval gate (`schemas/`) |
| Explicit Contracts | Typed schemas (`schemas/contracts.py`) |
| Evolutionary Architecture | LLM provider pluggable (`providers/`) |

## 🔄 Roadmap

- **Phase 1** ✅ — Gemini + local approval
- **Phase 2** — AWS Bedrock + DynamoDB + AgentCore
- **Phase 3** — Multi-guild, RBAC, Dashboard
