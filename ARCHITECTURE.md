# AuraFactory — Architecture v6

> **Version 6.0** | ReAct Agentic Architecture  
> References: AWS Well-Architected Agentic AI Lens | ReAct (Yao et al. 2023)

---

## Overview

AuraFactory is an AI Agent that automates Discord server setup and administration. A single **UnifiedAgent** processes natural language commands through a **ReAct loop** (Reason → Act → Observe → Think), executing Discord operations via MCP protocol.

```
┌─────────────────────────────────────────────────────────┐
│                     USER REQUEST                         │
│   Discord Bot (@mention)  │  Web Dashboard  │  REST API │
└──────────────────────────────────┬──────────────────────┘
                                   │
    ┌──────────────────────────────▼──────────────────────┐
    │  L1  Interface Layer     — Discord Bot, REST API    │
    │  L2  Gateway             — Auth, Safety, Rate-limit │
    │  L3  Agent (ReAct)       — Understand → Act → Think │
    │  L4  Tools & Skills      — MCP + Spec-driven        │
    │  L5  Connectors          — Discord API (**kwargs)   │
    │  L6  Memory & Context    — Server state, history    │
    │  L7  Infrastructure      — LLM, DB, Observability   │
    └─────────────────────────────────────────────────────┘
```

---

## State Machine

```
IDLE → UNDERSTAND → ACT (ReAct loop) → EVALUATE → RESPOND
                        ↕ AWAITING_CLARIFY  (resume → UNDERSTAND)
                        ↕ AWAITING_APPROVAL (resume → ACT at paused step)
```

---

## Layer 1 — Interface Layer

**Responsibility:** Accept user input, normalize, dispatch to agent.

| Adapter | File | Protocol |
|---------|------|----------|
| Discord Bot | `app/interfaces/discord_bot.py` | @mention / DM |
| Web Dashboard | `app/interfaces/api_routes.py` | REST + OAuth2 |

---

## Layer 2 — Gateway & Safety

**Responsibility:** Validate, rate-limit, and guard every request.

| Concern | Implementation | File |
|---------|---------------|------|
| Auth (Discord OAuth2) | Token validation + RBAC | `app/services/auth_service.py` |
| Guild Lock | Whitelist or open mode | `app/core/safety.py` → `GuildLock` |
| Rate Limiting | Token bucket per-guild | `app/core/middleware.py` → `RateLimitMiddleware` |
| Input Guardrails | Injection detection | `app/core/safety.py` → `InputGuardrail` |
| Token Budget | Daily cap per-guild | `app/core/safety.py` → `TokenBudget` |
| Audit Trail | All actions logged | `app/core/safety.py` → `AuditLogger` |

---

## Layer 3 — Agent Orchestration (ReAct)

**File:** `app/services/unified_agent.py` (998 lines)

### Flow

```
User Message
  │
  ▼
UNDERSTAND (1 LLM call)
  │ LLM outputs JSON: {action: "execute", tool_calls: [...]}
  │
  ▼
EXECUTE LOOP (ReAct)
  │
  │  ┌──────────────────────────────────┐
  │  │  for each tool in plan:          │
  │  │    1. ACT — execute single tool  │
  │  │    2. OBSERVE — record result    │
  │  │    3. THINK — LLM decides:       │
  │  │       • "proceed" → next tool    │
  │  │       • "adapt" → new plan       │
  │  │       • "stop" → done early      │
  │  └──────────────────────────────────┘
  │
  ▼
EVALUATE (1 LLM call)
  │ LLM sees all results → done / continue / ask_user / failed
  │
  ▼
RESPOND → User
```

### Token Optimization

| Scenario | LLM calls | Observe calls |
|----------|:---------:|:-------------:|
| Simple (≤2 tools, all success) | 2 | 0 (fast path) |
| Complex (>2 tools, all success) | 2 + N-1 | N-1 per-step |
| Tool failure (any plan size) | 2 + 1 | 1 (on failure) |

**Fast path rule:** If ≤2 tools planned and all succeed → skip per-step LLM observe (same cost as v5).

### Approval Gate

| Risk Level | Example | Behavior |
|------------|---------|----------|
| LOW/MEDIUM | Create channel, edit role | Execute immediately |
| HIGH | Delete channel, kick, ban | Pause → `AWAITING_APPROVAL` → User confirms |

Risk levels derived from `tools_spec.yaml` — zero hardcoding.

### Auto-Recovery: Community Feature

When a tool fails with `[community_required]`:
1. Auto-call `discord.guild.set_community(enable=True)`
2. Invalidate context cache
3. Retry original tool
4. If enable fails → surface error to LLM EVALUATE

---

## Layer 4 — Tools & Skills

### tools_spec.yaml (Source of Truth)

Generates:
- LLM function-call schemas (MCP ToolDefinition)
- NetworkX dependency graph (top-k tool retrieval)
- Runtime kwargs whitelist (validation)
- Risk levels (approval gate)
- Rate-limit profiles

| Component | File | Purpose |
|-----------|------|---------|
| Spec Loader | `app/core/spec_loader.py` | Parse YAML → `SpecRegistry` |
| Tool Graph | `app/core/tool_graph.py` | Vietnamese keyword → tool mapping |
| kwargs Filter | `app/core/kwargs_filter.py` | Whitelist + coerce params |
| Tool Definitions | `app/core/tool_definitions.py` | LLM schema generation |
| Normalizer | `app/core/normalizer.py` | Consistent LLM output shape |
| Skill Loader | `app/core/skill_loader.py` | Load .md skill files for context |

### 19 Connector Modules

channels, categories, roles, members, guild, webhooks, threads, invites, automod, backup, features, events, emojis, stickers, soundboard, onboarding, audit, safety, templates

### MCP Protocol

```
LLM → function_call("create_channel", {name, type, ...})
    → MCPClient.route("discord.channels.create")
    → ChannelsConnector.execute(guild, **kwargs)
    → Nextcord API
```

| File | Role |
|------|------|
| `app/mcp/protocol.py` | MCP types (Request, Response, ToolDefinition) |
| `app/mcp/client.py` | Route tool calls to servers |
| `app/mcp/servers/discord_server.py` | Discord MCP server (registers all tools) |

---

## Layer 5 — Connectors

**Pattern:** Class-based with `**kwargs` pass-through.

```python
class ChannelsConnector(BaseConnector):
    async def execute(self, action: str, guild: Guild, **kwargs) -> Dict:
        # Dispatch to action method
        # kwargs validated by KwargsFilter BEFORE reaching here

    async def create(self, guild, name, type="text", **kwargs) -> Dict:
        # Extract permission params → build overwrites
        # Spread remaining kwargs to Nextcord API
```

| File | Role |
|------|------|
| `app/connectors/base.py` | BaseConnector + helpers (build_overwrites, channel_to_dict) |
| `app/connectors/discord/connector.py` | Facade — routes `discord.{module}.{action}` |
| `app/connectors/discord/{module}.py` | 19 connector modules |
| `app/connectors/discord/exceptions.py` | Typed errors (CommunityRequiredError) |

### Error Contract

| Exception | Meaning | Agent Action |
|-----------|---------|-------------|
| `ValueError` | Bad input | Inform user |
| `PermissionError` | Bot lacks permission | Explain + suggest |
| `RuntimeError` | API failure | Auto-retry |
| `CommunityRequiredError` | Feature gate | Auto-enable + retry |

### Middleware Pipeline

```
Request → ErrorBoundary → RateLimit → Retry → Audit → Memory → [Execute]
```

---

## Layer 6 — Memory & Context

| Component | Implementation | File |
|-----------|---------------|------|
| Server Context | Cached guild state (channels, roles, categories) | `app/services/context_service.py` |
| Conversation Memory | Sliding window (6 turns) | `app/core/safety.py` → `ConversationMemory` |
| Knowledge Store | Per-guild SQLite (RAG-ready) | `app/data/knowledge_store.py` |
| Redis Cache | Optional (fallback: in-memory) | `app/data/redis_cache.py` |
| Guild Sync | Auto-update on Discord events | `app/services/guild_sync_service.py` |

---

## Layer 7 — Infrastructure

| Component | Current | Future (Phase 2) |
|-----------|---------|-------------------|
| LLM | Gemini 2.5 Flash | AWS Bedrock (multi-model) |
| Database | PostgreSQL (Render) | RDS / DynamoDB |
| Deployment | Render.com (Docker) | AWS ECS |
| Observability | Prometheus + JSON Logger | CloudWatch + X-Ray |
| Cache | Redis (optional) | ElastiCache |

### LLM Configuration

```
Model: gemini-2.5-flash
Temperature: 0.2 (understand), 0.1 (observe/evaluate), 0.7 (assemble)
Max tokens: 2048 (understand), 1024 (observe/evaluate), 512 (assemble)
Safety: BLOCK_NONE (required for Discord admin commands)
```

---

## Project Structure

```
AuraFactory/
├── app/
│   ├── config.py                 ← Environment config (singleton)
│   ├── main.py                   ← FastAPI entrypoint
│   ├── database.py               ← PostgreSQL async pool
│   ├── messages.py               ← Bilingual message templates (vi + en)
│   ├── core/
│   │   ├── kwargs_filter.py      ← Runtime kwargs validation
│   │   ├── middleware.py         ← Execution pipeline (5 middlewares)
│   │   ├── normalizer.py         ← LLM output normalization
│   │   ├── observability.py      ← Prometheus metrics
│   │   ├── request_lifecycle.py  ← Request state machine
│   │   ├── safety.py             ← GuildLock, RateLimiter, AuditLogger
│   │   ├── skill_loader.py       ← Load .md skills for context
│   │   ├── spec_loader.py        ← Parse tools_spec.yaml → registry
│   │   ├── tool_definitions.py   ← Generate LLM function schemas
│   │   └── tool_graph.py         ← NetworkX tool retrieval graph
│   ├── connectors/
│   │   ├── base.py               ← BaseConnector + shared helpers
│   │   └── discord/              ← 19 connector modules + exceptions
│   ├── data/
│   │   ├── knowledge_store.py    ← Per-guild SQLite knowledge
│   │   └── redis_cache.py        ← Redis cache layer
│   ├── interfaces/
│   │   ├── api_routes.py         ← REST API + OAuth2 + WebSocket
│   │   └── discord_bot.py        ← Discord bot adapter
│   ├── llm/
│   │   ├── base.py               ← Abstract LLM interface
│   │   └── gemini.py             ← Gemini implementation
│   ├── mcp/
│   │   ├── client.py             ← MCP routing client
│   │   ├── protocol.py           ← MCP types
│   │   └── servers/
│   │       └── discord_server.py ← Discord MCP server
│   └── services/
│       ├── unified_agent.py      ← THE agent (v6 ReAct)
│       ├── context_service.py    ← Server state cache
│       ├── auth_service.py       ← Discord OAuth2
│       ├── guild_sync_service.py ← Guild event sync
│       └── _token_tracker.py     ← Token usage tracking
├── skills/                       ← 9 markdown skill files (agent context)
├── migrations/                   ← 15 PostgreSQL migrations
├── frontend/                     ← Web dashboard (HTML/CSS/JS)
├── tests/                        ← pytest suite
├── tools_spec.yaml               ← Tool definitions (source of truth)
├── Dockerfile                    ← Production container
├── docker-compose.yml            ← Local dev stack
├── render.yaml                   ← Render.com deployment config
└── requirements.txt              ← Production dependencies
```

---

## Design Principles

1. **Zero dead-end** — Every branch leads to a result (no infinite loops)
2. **Goal-aware** — effective_goal persists across turns
3. **Dependency-resolved** — `$stepN.field` forward injection between tools
4. **Single LLM contract** — 1 system prompt, structured JSON output
5. **Bounded** — MAX_ITERATIONS=5, MAX_TOOL_CALLS=20, MAX_LLM_CALLS=8
6. **Resumable** — Pending state with 15-min TTL (DB-backed)
7. **Fail-safe** — Parse-retry on malformed LLM output, graceful degradation
8. **Token-efficient** — Fast path skips LLM calls when possible

---

## Changelog (from v5)

| Change | v5 (Batch) | v6 (ReAct) |
|--------|-----------|-------------|
| Execute loop | Batch all → evaluate at end | 1 tool → observe → decide → next |
| Mid-execution reasoning | None | `_observe_and_decide()` per-step |
| Plan adaptation | Only at EVALUATE | Can adapt mid-execution |
| Failure handling | Evaluate sees all failures at once | Immediate LLM decision on failure |
| Community recovery | Manual (user must enable) | Auto-detect → enable → retry |
| System prompt | External file (`prompts/`) | Inline in `unified_agent.py` |
| Token cost (simple) | Same | Same (fast path) |
| Token cost (complex) | Lower | +1-3 LLM calls (smarter) |
