# AuraFactory — 7-Layer Architecture

> **Version 2.1** | Consolidated from architecture.md (v1 theory) + architecture_v2.md (product focus) References: AWS Well-Architected Agentic AI Lens | ProtonX AgentBook 7-Layer Model

---

## Overview

AuraFactory is an AI Agent platform for Discord server administration and automation. It operates in **3 modes** (Setup → Assistant → Admin) across a **7-layer architecture**.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        USER REQUEST                                  │
│   Discord Bot (@mention)  │  Web Dashboard  │  REST API             │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
       ┌───────────────────────────▼───────────────────────────┐
       │  L1  Channel Layer        — Adapters & Input Normalize │
       │  L2  Gateway              — Auth, Safety, Rate-limit   │
       │  L3  Orchestration        — Classify, Plan, Execute    │
       │  L4  Skills & Tools       — MCP Registry + Spec-driven │
       │  L5  Connectors           — Discord API wrappers       │
       │  L6  Memory & Knowledge   — Working + Long-term + RAG  │
       │  L7  Infrastructure       — LLM, Queue, Observability  │
       └───────────────────────────────────────────────────────┘

```

---

## Layer 1 — Channel Layer (Input Adapters)

**Responsibility:** Accept user interactions from any source, normalize into a standard internal format.

| Adapter | File | Status |
| --- | --- | --- |
| Discord Bot | `app/interfaces/discord_bot.py` | ✅ Primary |
| Web Dashboard (REST) | `app/interfaces/api_routes.py` | ✅ Secondary |
| REST API (OpenAPI) | Same as above | ✅ |

**Output format** (standard for all channels):

```python
{
    "message": str,          # User's natural language input
    "guild_id": int,         # Target Discord server
    "user_id": int,          # Who sent it
    "role": "admin|member",  # Resolved from Discord roles
    "source": "discord|web", # Which adapter
    "session_id": str,       # For conversation continuity
}

```

**Event listeners** (proactive triggers, not user-initiated):

- `guild_create` → Trigger Setup Mode
- `member_join` → Trigger Onboarding DM
- `channel_*/role_*` → Auto-update Server Knowledge

---

## Layer 2 — Gateway & Control Plane

**Responsibility:** Validate, secure, and enrich every request before it reaches the brain.

| Concern | Implementation | File |
| --- | --- | --- |
| Authentication | Discord OAuth2 + bot token | `app/services/auth_service.py` |
| Authorization | Role-based (admin/mod/member) | `app/core/safety.py` → `GuildLock` |
| Rate Limiting | Token bucket (burst=5, delay=0.5s) | `app/core/safety.py` → `RateLimiter` |
| Input Guardrails | Prompt injection detection | `app/core/safety.py` |
| Cost Tracking | Token counting per-request | `app/core/middleware.py` |
| Trace ID | UUID per request | `app/core/request_lifecycle.py` |
| Session Management | PostgreSQL sessions table | `app/database.py` |
| Audit Logging | Full trail of actions | `app/core/safety.py` → `AuditLogger` |

**Gate logic:** Request passes ALL checks → forwarded to Layer 3. Any violation → blocked with error.

---

## Layer 3 — Agent Orchestration (The Brain)

**Responsibility:** Understand intent, plan actions, execute tools, reflect on results.

### Single Orchestrator, 3 Modes

```
                    ┌──────────────────────┐
                    │   UnifiedAgent v3.1  │
                    │  (app/services/      │
                    │   unified_agent.py)  │
                    └──────────┬───────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
     ┌────────▼──────┐ ┌──────▼──────┐ ┌───────▼───────┐
     │  SETUP MODE   │ │  ASSISTANT  │ │  ADMIN MODE   │
     │  (first-time) │ │  (24/7 Q&A) │ │  (on-demand)  │
     └───────────────┘ └─────────────┘ └───────────────┘

```

| Mode | Trigger | Target | Actions |
| --- | --- | --- | --- |
| **Setup** | Bot joins server (first time) | Admin | Conversational wizard → generate plan → confirm → batch execute |
| **Assistant** | Default state (any member mentions bot) | All members | RAG Q&A from Server Knowledge, onboarding DMs |
| **Admin** | Admin intent = command | Admin only | ReAct loop: Plan → [Approval] → Execute → Reflect → Assemble |

### Agentic Loop (Admin Mode)

```
Request → LLM Planning → [Approval Gate] → Execute Tools
       → Observe Results → Reflect (goal achieved?)
       → If not: Replan → Execute → Reflect (max 5 iterations)
       → Assemble friendly response

```

**Key constraints:**

- Max 5 iterations per request (configurable)
- Token budget per request
- Bounded autonomy: high-risk actions → Human-in-the-Loop confirmation

### Approval Gate

| Risk Level | Actions | Behavior |
| --- | --- | --- |
| LOW | Create channel, rename, list | Execute immediately |
| MEDIUM | Edit permissions, create role | Execute (show plan) |
| HIGH | Delete channel/role, kick, ban | Require explicit confirmation |
| CRITICAL | Bulk ban, restore backup | Double confirm |

Derived automatically from `tools_spec.yaml` `risk_level` field — zero hardcoding.

---

## Layer 4 — Skills & Tools Registry

**Responsibility:** Define what the Agent can do. Single source of truth.

### tools_spec.yaml (1200+ lines, 80 tools)

```yaml
# Generates:
#   1. LLM function-call schemas (MCP ToolDefinition)
#   2. NetworkX dependency graph (tool retrieval)
#   3. Runtime kwargs whitelist (validation)
#   4. Risk levels (approval gate)
#   5. Rate-limit profiles
#   6. Error taxonomy

```

| Component | File | Purpose |
| --- | --- | --- |
| Spec Loader | `app/core/spec_loader.py` | Parse YAML → `SpecRegistry` |
| Tool Graph | `app/core/tool_graph.py` | NetworkX graph for top-k retrieval |
| kwargs Filter | `app/core/kwargs_filter.py` | Runtime validation (whitelist + coerce) |
| Tool Definitions | `app/core/tool_definitions.py` | LLM schema generation |
| Normalizer | `app/core/normalizer.py` | Guarantee consistent LLM output shape |

### 19 Tool Modules

| Module | Actions | Coverage |
| --- | --- | --- |
| channels | create, edit, delete, move, list | ✅ |
| categories | create, edit, delete, sync, reorder, list | ✅ |
| roles | create, modify, delete, assign, remove, batch, clone | ✅ |
| members | kick, ban, unban, bulk_ban, timeout, mute, purge | ✅ |
| guild | get_info, edit_profile, set_verification, set_system_channels | ✅ |
| webhooks | create, delete, list | ✅ |
| threads | create, archive, delete | ✅ |
| invites | create, delete, list | ✅ |
| automod | create_rule, delete_rule, list_rules | ✅ |
| backup | export, restore | ✅ |
| features | setup_verification, create_poll, welcome, auto_delete | ✅ |
| events | create, edit, delete, list | ✅ |
| emojis | create, rename, delete, list | ✅ |
| stickers | create, delete, list | ✅ |
| soundboard | create, delete, list | ✅ |
| onboarding | get, setup | ✅ |
| audit | query | ✅ |
| safety | set_content_filter, set_mfa | ✅ |
| templates | create, sync, delete | ✅ |

### MCP Protocol

All tools are exposed via MCP (Model Context Protocol):

- Phase 1: In-process (direct function call wrapped via MCP interface)
- Phase 2: MCP over stdio/SSE (tools as separate processes)

```
LLM → function_call("create_channel", {name, type, ...})
    → MCPClient.route("discord.channels.create")
    → DiscordConnector.execute(guild, **kwargs)
    → Nextcord API

```

---

## Layer 5 — Connectors (External System Integration)

**Responsibility:** Translate tool calls into real API actions. Handle errors, retries, permissions.

### Architecture Pattern

```python
class XxxConnector(BaseConnector):
    async def execute(self, action: str, guild: Guild, **kwargs) -> Dict[str, Any]:
        # Dispatch to action method
        # All optional params flow through **kwargs
        # KwargsFilter validates BEFORE this runs

```

| File | Role |
| --- | --- |
| `app/connectors/base.py` | `BaseConnector` + shared helpers (parse_color, build_overwrites, etc.) |
| `app/connectors/discord/connector.py` | Facade — routes `discord.{module}.{action}` to correct connector |
| `app/connectors/discord/{module}.py` | 19 individual connector modules |

### Error Contract (consistent across all connectors)

| Exception | Meaning | Agent Action |
| --- | --- | --- |
| `ValueError` | Bad input (invalid ID, missing param) | Inform user |
| `PermissionError` | Bot lacks Discord permission | Explain + suggest fix |
| `RuntimeError` | API/network failure | Auto-retry with backoff |

### Middleware Pipeline

```
Request → ErrorBoundary → RateLimit → Retry → Audit → Memory → [Execute] → back up

```

Defined in `app/core/middleware.py` — composable chain, each middleware handles ONE concern.

---

## Layer 6 — Memory & Knowledge

**Responsibility:** Maintain context, remember preferences, serve factual answers.

### Memory Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Layer A: Working Memory (per-session, volatile)        │
│  • Conversation buffer (sliding window + summary)       │
│  • Reasoning scratchpad (JSON state during execution)   │
├─────────────────────────────────────────────────────────┤
│  Layer B: Server Knowledge (per-guild, persistent)      │
│  • Structured: channels, roles, categories, info (JSON) │
│  • Unstructured: pinned messages, rules, events (RAG)   │
│  • Auto-updated via Discord event listeners             │
├─────────────────────────────────────────────────────────┤
│  Layer C: Long-term Memory (cross-session)              │
│  • Semantic: facts about user/server preferences        │
│  • Procedural: learned patterns (skip confirm for X)    │
│  • Episodic: past interactions (decays over time)       │
└─────────────────────────────────────────────────────────┘

```

| Component | Phase 1 (Local) | Phase 2 (AWS) |
| --- | --- | --- |
| Conversation | PostgreSQL JSONB | DynamoDB |
| Server Knowledge (structured) | `context_service.py` cache | DynamoDB |
| Server Knowledge (RAG) | ChromaDB / BM25 | Bedrock Knowledge Bases |
| Long-term Memory | Not yet implemented | Bedrock + Qdrant |

### Context Service

`app/services/context_service.py` provides server state to the LLM prompt:

- Categories (max 20)
- Channels (max 40)
- Roles (max 20)
- Server info (name, member count, boost level, features)

Token-budgeted: fits within ~800 tokens alongside system prompt.

---

## Layer 7 — Infrastructure & Security

**Responsibility:** LLM access, deployment, observability, resilience.

| Component | Phase 1 | Phase 2 |
| --- | --- | --- |
| **LLM Gateway** | Gemini 2.5 Flash (free tier) | AWS Bedrock (multi-model) |
| **Database** | PostgreSQL (Render) | DynamoDB |
| **Vector Store** | ChromaDB (embedded) | Qdrant Cloud / Bedrock KB |
| **Deployment** | Render.com (Docker) | AWS ECS / Lambda |
| **Observability** | Python logging + audit table | CloudWatch + X-Ray traces |
| **Message Queue** | In-process asyncio | SQS |

### LLM Configuration (from tools_spec.yaml)

```yaml
defaults:
  max_iterations: 5
  temperature_planning: 0.2
  temperature_reflect: 0.1
  temperature_assemble: 0.7
  rate_limit_burst: 5
  rate_limit_min_delay: 0.5
  retry_max_attempts: 3

```

### Graceful Degradation

| Failure | Behavior |
| --- | --- |
| LLM unavailable | Return cached response or "service temporarily unavailable" |
| Discord API down | Queue actions, retry with backoff |
| Database down | Stateless mode (no history, still functional) |
| Memory store down | Skip memory retrieval, operate without context |

---

## Cross-cutting Concerns

### Prompt Management

| Prompt | File | Purpose |
| --- | --- | --- |
| `UNIFIED_SYSTEM_PROMPT` | `app/prompts/system_prompt.py` | Agent personality + capabilities + rules |
| `PLANNER_PROMPT` | Same file | Decompose request into tool calls |
| `REFLECT_PROMPT` | Same file | Evaluate if goal is achieved |
| `ASSEMBLE_PROMPT` | Same file | Format friendly response from results |

### Cost Control

- Token counting per request (input + output)
- Model routing: use smallest sufficient model
- Max iterations cap prevents runaway loops
- Daily budget alerts (Phase 2)

### Evaluation

- Online: success rate, latency per tool
- Offline: golden dataset regression tests (Phase 2)
- Shadow mode for prompt changes (Phase 2)

---

## Project Structure (Mapped to Layers)

```
AuraFactory/
├── tools_spec.yaml              ← L4: Single Source of Truth
├── ARCHITECTURE.md              ← This file
├── app/
│   ├── config.py                ← L7: Environment config
│   ├── main.py                  ← L7: FastAPI entrypoint
│   ├── database.py              ← L7: PostgreSQL
│   ├── messages.py              ← L1: Bilingual message templates
│   ├── core/                    ← L2+L3+L4: Brain
│   │   ├── spec_loader.py       ← L4: Parse tools_spec.yaml
│   │   ├── tool_graph.py        ← L4: NetworkX retrieval graph
│   │   ├── kwargs_filter.py     ← L4: Runtime kwargs validation
│   │   ├── tool_definitions.py  ← L4: LLM schema generation
│   │   ├── normalizer.py        ← L3: Guarantee LLM output shape
│   │   ├── middleware.py        ← L2: Execution pipeline
│   │   ├── request_lifecycle.py ← L2: Request state machine
│   │   └── safety.py            ← L2: ApprovalGate, RateLimiter, GuildLock, AuditLogger
│   ├── connectors/              ← L5: External system wrappers
│   │   ├── base.py              ← Shared helpers
│   │   └── discord/
│   │       ├── connector.py     ← Facade (19 modules)
│   │       ├── channels.py      ├── categories.py
│   │       ├── roles.py         ├── members.py
│   │       ├── guild.py         ├── webhooks.py
│   │       ├── threads.py       ├── invites.py
│   │       ├── automod.py       ├── backup.py
│   │       ├── features.py      ├── events.py
│   │       ├── emojis.py        ├── stickers.py
│   │       ├── soundboard.py    ├── onboarding.py
│   │       ├── audit.py         ├── safety.py
│   │       └── templates.py
│   ├── interfaces/              ← L1: Input adapters
│   │   ├── discord_bot.py       ← Discord Bot adapter
│   │   └── api_routes.py        ← REST API adapter
│   ├── llm/                     ← L7: LLM providers
│   │   ├── base.py              ← Abstract LLM interface
│   │   └── gemini.py            ← Google Gemini implementation
│   ├── mcp/                     ← L4: MCP protocol layer
│   │   ├── client.py            ← MCP client (routes tool calls)
│   │   ├── protocol.py          ← MCP types (Request, Response, ToolDef)
│   │   └── servers/
│   │       └── discord_server.py ← MCP server for Discord tools
│   ├── prompts/                 ← L3: LLM personality
│   │   └── system_prompt.py     ← All prompts (system, plan, reflect, assemble)
│   └── services/                ← L3+L6: Business logic
│       ├── unified_agent.py     ← THE orchestrator (v3.1)
│       ├── context_service.py   ← L6: Server knowledge cache
│       ├── auth_service.py      ← L2: OAuth2 flow
│       └── guild_sync_service.py ← L6: Guild state sync
├── frontend/                    ← L1: Web dashboard
│   ├── index.html
│   ├── static/style.css
│   └── templates/
│       ├── dashboard.html       ← Main chat UI
│       ├── login.html           ← Discord OAuth login
│       └── callback.html        ← OAuth callback handler
├── migrations/                  ← L7: Database schema
├── tests/                       ← Quality assurance
└── Dockerfile / docker-compose  ← L7: Deployment

```

---

## What Was Removed (vs v1 architecture.md)

| Removed | Reason |
| --- | --- |
| Multi-agent system (Architect, Moderator, DevOps, Copilot as separate agents) | Simplified to single UnifiedAgent with 3 modes. Cleaner, fewer tokens, same capability. |
| A2A Protocol (Agent-to-Agent) | No inter-agent communication needed with single orchestrator |
| Agent Identity & separate credentials per agent | Single bot token is sufficient |
| Conflict Resolution (optimistic locking between agents) | No concurrent agents |
| Memory Consolidation Pipeline (4-step async) | Phase 2 feature, not implemented yet |
| Episodic/Procedural Memory detailed specs | Phase 2 feature |
| Prompt Versioning system | Overkill for current scale |
| Prompt Drift Detection | Phase 2 feature |
| Shadow mode testing | Phase 2 feature |
| GraphRAG (entity-relationship multi-hop) | Phase 2 feature |

---

## What Was Added (vs v1)

| Added | Reason |
| --- | --- |
| 3 Bot Modes (Setup/Assistant/Admin) | Clear product lifecycle |
| Server Knowledge Store (per-guild) | Enables Assistant Q&A |
| Event-driven updates (auto-sync) | Keep knowledge fresh |
| Middleware Pipeline (composable) | Clean separation of cross-cutting concerns |
| tools_spec.yaml enhancements (error_taxonomy, rate_limit_profiles, param_aliases, blocked_actions) | Production hardening |
| 5 new connector modules (events, emojis, stickers, soundboard, onboarding) | Spec coverage |

