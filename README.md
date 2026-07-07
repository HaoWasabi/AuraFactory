# 🏭 AuraFactory

> **AI Agent tự động hoá setup & quản lý Discord server qua ngôn ngữ tự nhiên**  
> Plan-then-Execute với Human-in-the-Loop Approval  
> Track: Built with AWS (AABW Hackathon, Jul 8–12 2026)

---

## 💡 Giá trị cốt lõi

> Admin đăng nhập bằng Discord → chọn server → mô tả điều muốn làm → Bot lên kế hoạch → Admin duyệt (web hoặc Discord) → Bot tự thực thi hết.

**Không phải thin wrapper vì:**
- Bot **thực sự thực thi** trên Discord API (tạo channel, role, set permission)
- Có **pipeline xử lý** rõ ràng (classify → plan → approve → execute → report)
- Có **risk assessment + HITL thật** — AI không tự ý thực hiện hành động nguy hiểm
- Có **state machine bền vững** (PostgreSQL) — resume được sau crash/restart

---

## 🏗️ Architecture (7-Layer)

```
┌──────────────────────────────────────────────────────────────┐
│  L7: INTERFACE LAYER (I/O only)                              │
│  ├── Discord Bot (nextcord) — mention-based interaction      │
│  └── Web Dashboard + REST API (FastAPI) — OAuth login        │
├──────────────────────────────────────────────────────────────┤
│  L6: SERVICE LAYER (Business Logic)                          │
│  ├── RequestService    — nhận input, check khoá 1-active     │
│  ├── ClassifierService — phân loại intent (1 LLM call)       │
│  ├── PlannerService    — sinh execution plan (1 LLM call)    │
│  ├── ApprovalService   — dùng chung web + Discord buttons    │
│  ├── ExecutorService   — thực thi plan step-by-step          │
│  ├── ReActStepHandler  — retry cục bộ khi step lệch kỳ vọng │
│  ├── QueryService      — trả lời read-only (no plan needed)  │
│  ├── ContextService    — cache server state (60s TTL)        │
│  ├── AuthService       — Discord OAuth2 flow                 │
│  └── GuildSyncService  — sync quyền admin + bot_installs     │
├──────────────────────────────────────────────────────────────┤
│  L5: CONNECTORS (Tool Implementations)                       │
│  └── discord/ — 15 sub-connectors (channels, roles, perms…)  │
├──────────────────────────────────────────────────────────────┤
│  L4: MCP (Model Context Protocol)                            │
│  ├── MCPClient — unified tool dispatch + risk filtering      │
│  └── DiscordMCPServer — 37 tools via MCP protocol            │
├──────────────────────────────────────────────────────────────┤
│  L3: MODELS (Pydantic v2)                                    │
│  └── schemas.py — Request, Plan, PlanStep, AuditEntry…       │
├──────────────────────────────────────────────────────────────┤
│  L2: INFRASTRUCTURE                                          │
│  ├── database.py — asyncpg pool + auto-migrations            │
│  └── llm/ — BaseLLM + GeminiLLM (swappable → Bedrock later) │
├──────────────────────────────────────────────────────────────┤
│  L1: CONFIGURATION                                           │
│  └── config.py — env vars, feature flags                     │
└──────────────────────────────────────────────────────────────┘
         DATA LAYER: PostgreSQL (DUY NHẤT) — 10 tables
```

---

## 📁 Project Structure

```
AuraFactory/
├── app/
│   ├── main.py                # 🚀 Entrypoint + DI wiring + lifespan
│   ├── config.py              # L1: Settings (env vars)
│   ├── database.py            # L2: asyncpg pool + migrations
│   │
│   ├── llm/                   # L2: LLM providers
│   │   ├── base.py            # BaseLLM abstract + LLMResponse
│   │   └── gemini.py          # Gemini 2.5 Flash provider
│   │
│   ├── models/                # L3: Pydantic schemas
│   │   └── schemas.py         # All data models + constants
│   │
│   ├── mcp/                   # L4: MCP protocol layer
│   │   ├── protocol.py        # ToolDefinition, MCPRequest/Response, RiskLevel
│   │   ├── client.py          # MCPClient + MCPServer base class
│   │   └── servers/
│   │       └── discord_server.py  # DiscordMCPServer (37 tools)
│   │
│   ├── connectors/            # L5: Tool implementations
│   │   └── discord/           # 15 sub-connectors
│   │       ├── channels.py, categories.py, roles.py
│   │       ├── permissions.py, members.py, webhooks.py
│   │       ├── emojis.py, invites.py, threads.py
│   │       ├── guild.py, onboarding.py, backup.py
│   │       ├── automod.py, features.py, templates.py
│   │       └── connector.py   # Facade (dispatch + discovery)
│   │
│   ├── services/              # L6: Business logic
│   │   ├── request_service.py
│   │   ├── classifier_service.py
│   │   ├── planner_service.py
│   │   ├── approval_service.py
│   │   ├── executor_service.py
│   │   ├── react_step_handler.py
│   │   ├── query_service.py
│   │   ├── context_service.py
│   │   ├── auth_service.py
│   │   └── guild_sync_service.py
│   │
│   └── interfaces/            # L7: I/O layer
│       ├── discord_bot.py     # Nextcord bot + approval buttons
│       └── api_routes.py      # FastAPI REST endpoints
│
├── migrations/                # PostgreSQL schema (10 files)
│   ├── 001_create_sessions.sql
│   ├── 002_create_requests.sql
│   ├── 003_create_plans.sql
│   ├── ...
│   └── 010_create_rate_limits.sql
│
├── skills/                    # Tool definitions (reference .md files)
├── prompts/                   # System prompts
├── frontend/                  # Web dashboard (HTML/JS)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml         # PostgreSQL 16
└── render.yaml                # Deploy config
```

---

## 🔄 Request Pipeline (Hybrid Plan + ReAct)

```
User Message
    │
    ▼
┌─ RequestService ─────────────────────────────────┐
│  Check 1-active-request lock (per guild+user)    │
└──────────────────────────────────────────────────┘
    │
    ▼
┌─ ClassifierService ──────────────────────────────┐
│  1 LLM call → intent + tool_mode + confidence    │
│  Intents: setup|manage|moderate|query|           │
│           server_settings|automod|clarify|oos    │
└──────────────────────────────────────────────────┘
    │
    ├── query → QueryService (read-only, no plan)
    ├── clarify/oos → direct response
    │
    ▼ (action intents)
┌─ PlannerService ─────────────────────────────────┐
│  1 LLM call → ordered steps [{tool, params}]     │
│  Risk = max(step risks)                          │
│  LOW/MEDIUM → auto-approve                       │
│  HIGH/CRITICAL → await human approval            │
└──────────────────────────────────────────────────┘
    │
    ▼ (approved)
┌─ ExecutorService ────────────────────────────────┐
│  For each step:                                  │
│    1. Call MCP tool                              │
│    2. If fail → ReActStepHandler (1 retry)       │
│    3. Write audit_log                            │
│  Progress reported after each step               │
└──────────────────────────────────────────────────┘
```

**ReAct boundary (§5.6b):** Khi 1 step fail, LLM được phép điều chỉnh THAM SỐ (cùng tool) — không thêm/bớt step, không đổi tool, max 1 retry.

---

## 🧠 Key Design Decisions

| Decision | Rationale |
|---|---|
| **Plan-then-Execute** (not pure ReAct) | User sees full plan BEFORE execution → transparent, auditable |
| **PostgreSQL only** | No Redis, no vector DB, no graph DB at Phase 1 — simplicity |
| **MCP protocol** | All tools go through unified interface → easy to add/swap |
| **1 LLM call per stage** | Classify=1 call, Plan=1 call, ReAct=1 call → predictable cost |
| **Dual-origin** (web + Discord) | Same pipeline, same approval service, same state |
| **Risk matrix + HITL** | LOW/MEDIUM auto-execute; HIGH/CRITICAL require explicit human approval |

---

## 🚀 Quick Start

```bash
# 1. Setup environment
cp .env.example .env
# Edit .env: DISCORD_TOKEN, GEMINI_API_KEY, DATABASE_URL, DISCORD_CLIENT_ID/SECRET

# 2. Start database
docker-compose up -d

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
uvicorn app.main:app --reload --port 8000
```

**Required env vars:**
```env
DISCORD_TOKEN=your_bot_token
GEMINI_API_KEY=your_gemini_key
DATABASE_URL=postgresql://localhost:5432/aurafactory
DISCORD_CLIENT_ID=your_client_id
DISCORD_CLIENT_SECRET=your_client_secret
DISCORD_REDIRECT_URI=http://localhost:8000/api/auth/callback
```

---

## 📊 Tech Stack

| Layer | Technology |
|---|---|
| Bot framework | nextcord |
| Web framework | FastAPI + Uvicorn |
| Database | PostgreSQL 16 (asyncpg) |
| LLM | Gemini 2.5 Flash (Phase 1) → Amazon Bedrock (Phase 2) |
| Auth | Discord OAuth2 |
| Deploy | Render / Docker |

---

## 🗺️ Roadmap

| Phase | Focus | LLM |
|---|---|---|
| **Phase 1** (hackathon) | Core pipeline + Discord bot + Web dashboard | Gemini 2.5 Flash |
| **Phase 2** (post-event) | Bedrock integration, Guardrails, CloudWatch | Amazon Bedrock |
| **Phase 3** (future) | Member assistant 24/7, RAG, vector search | Hybrid |

---

## 🏆 AABW Hackathon

- **Track:** Built with AWS
- **Dates:** July 8–12, 2026
- **Strategy:** Gemini chạy trước cho tới khi luồng ổn định → Bedrock tích hợp cuối
