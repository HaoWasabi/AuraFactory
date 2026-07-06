# 🏭 AuraFactory

> **Agentic AI — Tự động hóa Discord Workspace**  
> Multi-Agent System với Human-in-the-Loop Approval  
> Thiết kế theo AWS Well-Architected Agentic AI Lens

---

## 🏗️ Architecture

```
┌─────────────┐           ┌──────────────────────────────────────────────────────┐
│  Frontend   │  HTTP     │  FastAPI (app/main.py)                               │
│  (Browser)  │ ────────► │    ├── /chat        → Orchestrator pipeline          │
│             │ ◄──────── │    ├── /approvals   → HITL approval gate             │
└─────────────┘           │    ├── /skills      → Skills Registry status         │
                          │    ├── /metrics     → Prometheus metrics             │
                          │    └── /health      → System status                  │
                          └──────────────────────┬─────────────────────────────────┘
┌─────────────┐                             │
│  Discord    │  Mentions                   │
│  Server     │ ────────► app/channels/     │
└─────────────┘           discord_adapter   ┘
                               │
                    ┌──────────▼──────────┐
                    │  Gateway Layer      │
                    │  • Rate Limiter     │
                    │  • Guardrails       │
                    │  • Role Detection   │
                    │  • Session Manager  │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  OrchestratorAgent  │
                    │  (Classify → Route) │
                    │  + Memory Recall    │
                    └───┬────────────┬────┘
                        │            │
           ┌────────────▼──┐    ┌───▼────────────┐
           │  AdminAgent    │    │  AssistantAgent │
           │  (Setup/CRUD)  │    │  (Q&A/Onboard) │
           │  + SkillValid  │    │  + Knowledge   │
           └────────┬───────┘    └────────────────┘
                    │
           ┌────────▼────────┐
           │  SkillRegistry  │ → validate → risk check
           └────────┬────────┘
                    │
           ┌────────▼────────┐
           │  MCP Client     │ → route to correct server
           └───┬────────┬────┘
               │        │
    ┌──────────▼──┐  ┌──▼──────────┐
    │ Discord MCP │  │ Memory MCP  │
    │ (40+ tools) │  │ (recall/store)│
    └──────────┬──┘  └─────────────┘
               │
    ┌──────────▼──────────┐
    │  Discord API        │ ← execute only when risk ≤ MEDIUM
    │  (nextcord)         │   or Human has Approved
    └─────────────────────┘
```

---

## 📁 Project Structure

```
AuraFactory/
├── docker-compose.yml         # PostgreSQL 16
├── Makefile                   # make setup | dev | db-reset
├── requirements.txt
│
├── app/                       # Source code
│   ├── main.py                # 🚀 Entrypoint + DI Container
│   │
│   ├── channels/              # Layer 1 — Channel Adapters
│   │   ├── base.py            # Abstract adapter interface
│   │   ├── discord_adapter.py # nextcord bot events + send
│   │   └── api_adapter.py     # FastAPI POST /chat
│   │
│   ├── gateway/               # Layer 2 — Control Plane
│   │   ├── pipeline.py        # GatewayPipeline (rate limit → guard → role → session)
│   │   ├── guardrails.py      # Prompt injection detection
│   │   ├── rate_limiter.py    # Token-bucket (20 req/min/user)
│   │   ├── session_manager.py # Session resolution
│   │   └── cost_tracker.py    # Budget tracking
│   │
│   ├── agents/                # Layer 3 — Orchestration
│   │   ├── orchestrator.py    # Thin router (classify → route) + memory recall
│   │   ├── classifier.py      # Intent classification (LLM + fallback heuristic)
│   │   ├── admin_agent.py     # Setup wizard + CRUD ReAct loop + HITL
│   │   ├── assistant_agent.py # Q&A (RAG) + onboarding DM gen
│   │   ├── architect.py       # Specialist: multi-step Discord ops
│   │   ├── base.py            # BaseAgent (retry, tracing, metrics)
│   │   └── contracts.py       # TaskAssignment, TaskResult, AgentRole
│   │
│   ├── skills/                # Layer 4 — Skills Registry
│   │   ├── registry.py        # SkillRegistry (agent routing, risk, planning)
│   │   ├── loader.py          # Parse SKILL.md → SkillTool objects
│   │   ├── validator.py       # Validate params before execution
│   │   └── startup.py         # init_skills() at boot
│   │
│   ├── mcp/                   # Layer 5 — MCP (Model Context Protocol)
│   │   ├── protocol.py        # JSON-RPC types (ToolDefinition, Request, Response)
│   │   ├── client.py          # MCPClient (unified tool dispatch)
│   │   ├── server.py          # MCPServer ABC
│   │   └── servers/
│   │       ├── discord_server.py # 40+ Discord tools
│   │       ├── memory_server.py  # Memory recall/store tools
│   │       └── skills_server.py  # Composite workflow skills
│   │
│   ├── connectors/            # Layer 5b — Tool Implementations
│   │   └── discord/           # 16 modules (channels, roles, members, etc.)
│   │
│   ├── memory/                # Layer 6 — Memory
│   │   ├── service.py         # MemoryService facade
│   │   ├── working.py         # Short-term (session cache)
│   │   ├── episodic.py        # Past interactions (vector search)
│   │   ├── semantic.py        # Learned facts (vector search)
│   │   ├── procedural.py      # Trigger → action patterns
│   │   └── scoring.py         # Importance scoring
│   │
│   ├── knowledge/             # Layer 6b — Server Knowledge (RAG)
│   │   ├── store.py           # Per-guild knowledge CRUD (JSON Phase 1)
│   │   ├── crawler.py         # Crawl guild → extract knowledge
│   │   └── models.py          # ServerKnowledge, ChannelInfo, etc.
│   │
│   ├── infra/                 # Layer 7 — Infrastructure
│   │   ├── llm/               # LLM providers (Groq, Gemini, OpenRouter, Ollama)
│   │   ├── database/          # asyncpg pool + migrations
│   │   ├── cache/             # InMemoryCache
│   │   ├── embedding/         # Embedding provider
│   │   ├── vectorstore/       # Vector DB interface
│   │   ├── observability/     # Tracer, Metrics, Cost
│   │   └── queue/             # Async job queue (Phase 2)
│   │
│   ├── models/                # Shared data models
│   │   └── messages.py        # IncomingMessage, OutgoingMessage
│   │
│   └── config/                # Settings (env-based)
│
├── skills/                    # Skill definitions (SKILL.md files)
│   ├── discord_channels.md
│   ├── discord_roles.md
│   ├── discord_moderation.md
│   ├── discord_categories.md
│   ├── discord_permissions.md
│   ├── discord_webhooks.md
│   ├── discord_info.md
│   ├── discord_backup.md
│   └── discord_onboarding.md
│
├── prompts/                   # System prompts for agents
├── docs/                      # Architecture docs + specs
│   ├── specs/                 # Layer-by-layer specifications
│   └── steering/              # Coding conventions + rules
├── frontend/                  # Web chat UI
├── tests/                     # Test suite
└── data/                      # Runtime data (knowledge JSON, logs)
```

---

## 🧠 Key Design Decisions

### Multi-Agent (3 agents, not N)
- **OrchestratorAgent** — thin router (~50 lines logic). Classify → permission gate → route.
- **AdminAgent** — Setup wizard + CRUD. ReAct loop. MCP tools. SkillValidator gate.
- **AssistantAgent** — Pure Q&A. Zero side effects. Knowledge-based RAG.
- **ArchitectAgent** — Specialist called by AdminAgent for complex multi-step operations.

### MCP (Model Context Protocol) — Unified Tool Calling
All tool calls go through MCP. Benefits:
- Single interface for all tools (Discord, Memory, future integrations)
- Phase 1: in-process. Phase 2: swap to remote (stdio/SSE) with zero code change.
- Easy to add community MCP servers later.

### Skills Registry — Planning + Validation Layer
Sits between Agents and MCP:
- Provides **risk-aware** tool list for LLM planning
- **Validates** params before execution (type, required, enum, sanitization)
- **Agent routing** — each tool maps to architect or assistant
- Tool definitions in `.md` files — easy to edit without code changes

### HITL (Human-in-the-Loop) Approval
- Risk matrix per tool (low/medium/high/critical)
- HIGH+ risk → AdminAgent returns `CONFIRM` action → plan persisted in working memory
- User confirms → resume execution from saved plan

### Memory — 5-Type Cognitive Model
- **Working** — session cache (pending plans, temp state)
- **Episodic** — past interactions (vector search for similar situations)
- **Semantic** — learned facts ("this server prefers Vietnamese")
- **Procedural** — trigger→action patterns (auto-responses)
- **Knowledge** — crawled server structure (channels, roles, rules)

---

## 🚀 Quick Start

```bash
# 1. Setup
cp .env.example .env
# Edit .env with your tokens (DISCORD_TOKEN, GROQ_API_KEY, etc.)

# 2. Start database
docker-compose up -d

# 3. Install deps
pip install -r requirements.txt

# 4. Run
make dev
# or: uvicorn app.main:app --reload
```

---

## 📊 Stats
- **Tools**: 40+ Discord operations
- **LLM Providers**: Groq, Gemini, OpenRouter, Ollama (with auto-fallback)
- **Skills**: 9 skill definition files, 43 tool definitions
- **Architecture**: 7 layers, event-driven, multi-guild

---

## 🏆 AABW Hackathon
- **Track**: Built with AWS
- **Deadline**: July 8-12, 2026
- **Phase 1**: Open-source (current) → **Phase 2**: AWS integration (Bedrock, DynamoDB, etc.)
