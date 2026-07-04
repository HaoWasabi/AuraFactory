# 🏭 AuraFactory

> **Agentic AI — Tự động hóa Discord Workspace**  
> Multi-Agent System với Human-in-the-Loop Approval

---

## 🏗️ Architecture

```
┌─────────────┐    HTTP    ┌─────────────────────────────────────┐
│  Frontend   │ ─────────→ │  server.py (FastAPI)                │
│  (Browser)  │ ←───────── │    ├── /chat — main endpoint        │
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
                    │ Discord API  │ ← chỉ execute nếu Human Approve
                    └──────────────┘
```

## 📁 Project Structure

```
AuraFactory/
├── server.py              ← 🚀 ENTRY POINT — FastAPI + Discord bot
├── AFfrontend.html        ← Frontend UI (single-file React)
├── requirements.txt       ← Dependencies
├── welcome_config.json    ← Config cho welcome messages
│
├── agents/                ← 🧠 Agent System (AI Core)
│   ├── base_agent.py         BaseAgent + permission check
│   ├── orchestrator.py       Phân tích intent → route tasks
│   ├── architect_agent.py    Execute Discord operations
│   └── copilot_agent.py      Q&A / giải đáp
│
├── schemas/               ← 📋 Contracts + Rules
│   ├── contracts.py          TaskAssignment, TaskResult (typed)
│   ├── permissions.py        Risk levels + approval rules
│   └── approval.py           Human-in-the-loop approval store
│
├── providers/             ← 🔌 LLM Providers (pluggable)
│   ├── base.py               Abstract interface
│   ├── gemini_provider.py    Phase 1: Google Gemini (free)
│   └── bedrock_provider.py   Phase 2: AWS Bedrock (production)
│
├── tools/                 ← 🔧 Discord Operations
│   ├── discord_channel.py    Tạo/xóa/sửa channels
│   ├── discord_role.py       Quản lý roles
│   ├── discord_member.py     Quản lý members
│   ├── discord_category.py   Categories
│   ├── discord_guild.py      Server settings
│   ├── discord_webhook.py    Webhooks
│   ├── discord_backup.py     Backup/restore
│   └── discord_features.py   Feature flags
│
├── commands/              ← ⌨️ Slash Commands (Discord native)
│   ├── channel_command.py
│   ├── role_command.py
│   ├── member_command.py
│   └── ...
│
├── observability/         ← 📊 Tracing & Monitoring
│   └── tracer.py             Request tracing + audit log
│
├── config/                ← ⚙️ Settings
│   └── settings.py           Environment + constants
│
├── docs/                  ← 📄 Documentation
│   ├── privacy.md
│   ├── term.md
│   └── ui-plan.md
│
├── legacy/                ← 🗄️ Old code (reference only)
│   ├── app_v1.py             Entry point cũ (Discord-only)
│   ├── main_v1.py            Main cũ
│   ├── prompts_v1.py         Prompts cũ
│   └── core/                 Core logic cũ
│
└── test/                  ← 🧪 Tests
    └── bot_test.py
```

## 🚀 Quick Start

```bash
# 1. Install
pip install -r requirements.txt

# 2. Config (.env)
DISCORD_TOKEN=your_bot_token
GUILD_ID=your_server_id          # Right-click server → Copy Server ID
GEMINI_TOKEN=your_gemini_key

# 3. Run
python server.py

# 4. Open
# → http://localhost:8000/docs    (API docs)
# → Open AFfrontend.html         (Chat UI)
```

## 🛡️ Security: Human-in-the-Loop

| Action | Risk Level | Behavior |
|--------|-----------|----------|
| `list_channels` | 🟢 LOW | Auto-execute |
| `create_channel` | 🟡 MEDIUM | Auto-execute |
| `delete_channel` | 🔴 HIGH | **Block → Require Approval** |
| `delete_role` | 🔴 HIGH | **Block → Require Approval** |
| `kick_member` | 🔴 HIGH | **Block → Require Approval** |
| `ban_member` | 🔴 HIGH | **Block → Require Approval** |
| `transfer_ownership` | 🔴 CRITICAL | **Block → Require Approval** |

### Approval Flow:
```
User: "Xóa kênh general"
  → Orchestrator: plan đúng, route tới Architect
  → Architect: check permission → HIGH risk
  → System: TẠM DỪNG, tạo PendingApproval
  → Frontend: hiện nút [✅ Phê duyệt] [❌ Từ chối]
  → Admin click Approve
  → POST /approve/{id} → Agent execute → Channel deleted
```

## 🧪 API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/chat` | Gửi prompt, nhận kết quả |
| GET | `/health` | System status |
| GET | `/approvals` | Xem pending approvals |
| POST | `/approve/{id}` | Phê duyệt action |
| POST | `/reject/{id}` | Từ chối action |
| GET | `/traces/{id}` | Xem trace chi tiết |
| GET | `/guilds` | Liệt kê Discord servers |

## 📐 Design Principles (AWS Well-Architected + Agentic AI Lens)

1. **Explicit Contracts** — Typed schemas cho mọi agent communication
2. **Least Privilege** — Risk-based permissions, minimal Discord scopes
3. **Human Oversight** — High-risk actions MUST have approval
4. **Observable** — Every request traced end-to-end
5. **Provider-Agnostic** — Swap LLM provider without code changes
6. **Fail-Safe** — Default deny, timeout expired approvals

---

**Phase 1**: Gemini (free) ✅  
**Phase 2**: AWS Bedrock + DynamoDB + CloudWatch  
**Phase 3**: Multi-guild + RBAC + Dashboard
