# AuraFactory v2.1 🏭

**AI-Powered Discord Server Management** — Spec-driven Agentic Architecture

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  User Request (Discord mention / Dashboard)                      │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  UnifiedAgent v2                                                 │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌───────────────┐  │
│  │Guild Lock│→ │ LLM Call │→ │ Approval  │→ │ Rate Limiter  │  │
│  │(security)│  │(Gemini)  │  │   Gate    │  │ + Retry       │  │
│  └──────────┘  └──────────┘  └───────────┘  └───────────────┘  │
│                                                    │             │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐       ▼             │
│  │  Audit   │← │ Memory   │← │  Format   │← │MCP Execute│     │
│  │  Logger  │  │(context) │  │ Response  │  └───────────┘     │
│  └──────────┘  └──────────┘  └───────────┘                     │
└─────────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  MCP Server → Discord Connector Facade                           │
│  ┌──────────┐ ┌──────────┐ ┌────────┐ ┌─────────┐ ┌────────┐  │
│  │ Channels │ │  Roles   │ │Members │ │  Guild  │ │Features│  │
│  │ Category │ │  Assign  │ │  Mod   │ │Settings │ │  Polls │  │
│  └──────────┘ └──────────┘ └────────┘ └─────────┘ └────────┘  │
│  + Webhooks, Threads, Invites, AutoMod, Backup, Templates,      │
│    Audit, Safety, Events, Emojis, Stickers, Soundboard,         │
│    Onboarding                                                    │
└─────────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### Spec-Driven (**kwargs pattern**)
- Single source of truth: `tools_spec.yaml` (1200+ lines, 80+ tools)
- Tool code uses pure `**kwargs` — zero validation logic in connectors
- `KwargsFilter` (from spec) validates before execution
- `ToolGraph` (NetworkX) handles intelligent tool retrieval

### Safety Layers (Production)
1. **Guild Lock** — whitelist or open mode (`GUILD_LOCK_MODE=whitelist`)
2. **Approval Gate** — destructive actions (delete/ban/kick) ask user first
3. **Rate Limiter** — 0.5s delay between Discord API calls, burst=5
4. **Retry Policy** — exponential backoff (3 retries) on transient 5xx/429
5. **Audit Logger** — every tool execution logged (who, what, when, result)
6. **Conversation Memory** — tracks created resources for multi-turn references

### Token Efficiency
- 1 LLM call per request (Gemini native function calling)
- ~800-1200 tokens/request
- Future: top-k graph retrieval saves 90% tool context tokens

## Project Structure

```
AuraFactory/
├── tools_spec.yaml              ← SOURCE OF TRUTH (all tools defined here)
├── app/
│   ├── config.py                ← Environment config + safety settings
│   ├── main.py                  ← FastAPI entrypoint + lifespan
│   ├── database.py              ← PostgreSQL (Phase 2: DynamoDB)
│   ├── core/                    ← 🧠 Brain
│   │   ├── spec_loader.py      ← Parse tools_spec.yaml
│   │   ├── tool_graph.py       ← NetworkX dependency graph
│   │   ├── kwargs_filter.py    ← Runtime kwarg validation
│   │   ├── unified_agent.py    ← Graph-based orchestrator (Phase 2)
│   │   └── safety.py           ← All safety layers
│   ├── connectors/              ← 🔌 Discord API wrappers
│   │   ├── base.py             ← BaseConnector + shared helpers
│   │   └── discord/
│   │       ├── connector.py    ← Facade (dispatches to sub-connectors)
│   │       ├── channels.py     ← create, edit, delete, move, list
│   │       ├── categories.py   ← create, edit, delete, sync, reorder, list
│   │       ├── roles.py        ← create, modify, delete, assign, remove, batch, clone
│   │       ├── members.py      ← kick, ban, unban, bulk_ban, timeout, mute, purge
│   │       ├── guild.py        ← get_info, edit_profile, set_verification...
│   │       ├── webhooks.py     ← create, delete, list
│   │       ├── threads.py      ← create, archive, delete
│   │       ├── invites.py      ← create, delete, list
│   │       ├── automod.py      ← create_rule, delete_rule, list_rules
│   │       ├── backup.py       ← export, restore
│   │       ├── features.py     ← verification, polls, welcome, auto-delete
│   │       ├── audit.py        ← query audit logs
│   │       ├── safety.py       ← content filter, MFA
│   │       ├── events.py       ← scheduled events CRUD
│   │       ├── emojis.py       ← create, rename, delete, list
│   │       ├── stickers.py     ← create, delete, list
│   │       ├── soundboard.py   ← create, delete, list (REST-based)
│   │       ├── onboarding.py   ← get config, setup prompts
│   │       └── templates.py    ← create, sync, delete
│   ├── services/                ← 🔧 Business logic
│   │   ├── unified_agent.py    ← Main agent (v2 with safety)
│   │   ├── context_service.py  ← Server state cache
│   │   ├── auth_service.py     ← OAuth + session management
│   │   └── guild_sync_service.py
│   ├── interfaces/              ← 🖥️ Entry points
│   │   ├── discord_bot.py      ← Discord bot (mentions → agent)
│   │   └── api_routes.py       ← REST API for dashboard
│   ├── llm/                     ← 🤖 LLM abstraction
│   │   ├── base.py             ← BaseLLM interface
│   │   └── gemini.py           ← Gemini implementation
│   └── mcp/                     ← 📡 MCP protocol layer
│       ├── client.py           ← MCP client (tool dispatcher)
│       └── servers/
│           └── discord_server.py
├── frontend/                    ← Dashboard (static HTML/JS/CSS)
├── migrations/                  ← SQL migrations
├── tests/                       ← Test suite
├── Dockerfile                   ← Container build
├── docker-compose.yml           ← Local dev stack
└── render.yaml                  ← Render.com deployment
```

## Quick Start

```bash
# 1. Clone + install
git clone <repo>
cd AuraFactory
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your Discord token, Gemini API key, DB URL

# 3. Run
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DISCORD_TOKEN` | ✅ | — | Bot token from Discord Developer Portal |
| `GEMINI_API_KEY` | ✅ | — | Google AI API key |
| `GEMINI_MODEL` | ❌ | `gemini-2.5-flash` | Gemini model name |
| `DATABASE_URL` | ✅ | `postgresql://localhost:5432/aurafactory` | PostgreSQL connection |
| `ALLOWED_GUILD_IDS` | ❌ | — | Comma-separated guild IDs (for whitelist mode) |
| `GUILD_LOCK_MODE` | ❌ | `open` | `open` (all guilds) or `whitelist` |
| `RATE_LIMIT_DELAY` | ❌ | `0.5` | Seconds between API calls |
| `SECRET_KEY` | ❌ | `dev-secret...` | Session encryption key |
| `LOG_LEVEL` | ❌ | `INFO` | Logging level |

## Phases

### Phase 1 (Current) — Open Source
- ✅ Gemini Flash LLM (free tier: 1M tokens/day)
- ✅ PostgreSQL database
- ✅ NetworkX in-memory graph
- ✅ Full safety layers
- ✅ 19 Discord connector modules, 80+ actions
- ✅ Spec-driven validation (KwargsFilter + error_taxonomy)
- ✅ Rate-limit profiles (4 tiers: light/standard/heavy/critical)
- ✅ Middleware pipeline (ErrorBoundary → RateLimit → Retry → Audit → Memory)

### Phase 2 — AWS Integration
- 🔲 LLM: Gemini → AWS Bedrock (Claude/Titan)
- 🔲 Database: PostgreSQL → DynamoDB
- 🔲 Graph: NetworkX → AWS Neptune
- 🔲 Storage: Local → S3
- 🔲 Monitoring: File logs → CloudWatch
- 🔲 Retrieval: Keyword → Bedrock embedding top-k

## License

MIT
