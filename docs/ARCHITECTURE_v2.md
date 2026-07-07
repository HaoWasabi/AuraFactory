# AuraFactory — Architecture Redesign (Database-First)

**Date:** 2026-07-07 | **Approach:** Clean redesign, giữ MCP tools, database cho mọi state

---

## 1. Nguyên tắc thiết kế

| # | Nguyên tắc | Lý do |
| --- | --- | --- |
| 1 | **Database-first** — mọi state vào PostgreSQL | Không mất data khi restart, audit trail, resume được |
| 2 | **Giữ nguyên MCP tools** — chỉ rewire logic gọi | Đã test, chạy ổn, không viết lại |
| 3 | **Đơn giản hóa agent layer** — bỏ abstraction thừa | Code cũ quá nhiều layer → bug DI injection |
| 4 | **State machine rõ ràng** — mỗi request có trạng thái tracked | Biết đang ở đâu, resume được, không mất giữa chừng |
| 5 | **Separation of concerns** — Bot chỉ IO, logic ở service layer | Dễ test, dễ swap interface (Discord/API/Web) |

---

## 2. Architecture Overview

```
┌──────────────────────────────────────────────────────┐
│  INTERFACE LAYER (I/O only — nhận & gửi message)     │
│  ├── Discord Bot (nextcord)                          │
│  └── REST API (FastAPI) — cho dashboard              │
├──────────────────────────────────────────────────────┤
│  SERVICE LAYER (Business Logic)                      │
│  ├── RequestService    — nhận message, check quyền   │
│  ├── ClassifierService — phân loại intent            │
│  ├── PlannerService    — sinh execution plan         │
│  ├── ExecutorService   — thực thi plan step-by-step  │
│  └── QueryService      — trả lời read-only          │
├──────────────────────────────────────────────────────┤
│  DATA LAYER (PostgreSQL)                             │
│  ├── sessions          — context per user/guild      │
│  ├── requests          — mỗi user request tracked    │
│  ├── plans             — execution plans             │
│  ├── plan_steps        — từng step + status          │
│  ├── approvals         — pending/approved/rejected   │
│  ├── audit_log         — mọi tool call đã thực thi  │
│  └── server_snapshots  — cached server structure     │
├──────────────────────────────────────────────────────┤
│  TOOL LAYER (MCP — giữ nguyên)                       │
│  └── Discord MCP Server (37 tools)                   │
├──────────────────────────────────────────────────────┤
│  LLM LAYER (Swappable)                               │
│  ├── Gemini 2.5 Flash (Phase 1)                      │
│  └── Amazon Bedrock (Phase 2)                        │
└──────────────────────────────────────────────────────┘

```

---

## 3. Database Schema (PostgreSQL)

### 3.1. `sessions` — Quản lý conversation context

```sql
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    user_role VARCHAR(20) NOT NULL DEFAULT 'member',  -- owner/admin/moderator/member
    history JSONB DEFAULT '[]',         -- last N messages [{role, content, timestamp}]
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_active_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '30 minutes',
    
    UNIQUE(guild_id, user_id)
);

-- Auto-cleanup expired sessions
CREATE INDEX idx_sessions_expires ON sessions(expires_at);

```

### 3.2. `requests` — Track mỗi user request

```sql
CREATE TABLE requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES sessions(id),
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    
    -- Input
    message TEXT NOT NULL,
    intent VARCHAR(30),              -- FAST_TRACK / ADMIN_COMPLEX / ASSISTANT / NULL (pending)
    tool_mode VARCHAR(20),           -- setup / manage / moderate / query / full
    
    -- State machine
    status VARCHAR(20) NOT NULL DEFAULT 'received',
    -- received → classified → planned → awaiting_approval → executing → completed / failed
    
    -- Output
    response TEXT,                   -- final bot response
    error_message TEXT,              -- if failed
    
    -- Metadata
    llm_tokens_in INT DEFAULT 0,
    llm_tokens_out INT DEFAULT 0,
    llm_provider VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    
    CONSTRAINT valid_status CHECK (status IN (
        'received', 'classified', 'planned', 'awaiting_approval', 
        'executing', 'completed', 'failed', 'cancelled'
    ))
);

CREATE INDEX idx_requests_session ON requests(session_id);
CREATE INDEX idx_requests_status ON requests(status) WHERE status NOT IN ('completed', 'failed');

```

### 3.3. `plans` — Execution plans (cho ADMIN_COMPLEX)

```sql
CREATE TABLE plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID REFERENCES requests(id) ON DELETE CASCADE,
    guild_id BIGINT NOT NULL,
    
    -- Plan content
    description TEXT,                -- "Setup server học tiếng Anh"
    total_steps INT NOT NULL,
    risk_level VARCHAR(10) NOT NULL, -- LOW / MEDIUM / HIGH / CRITICAL
    
    -- State
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    -- draft → awaiting_approval → approved → executing → completed / failed / cancelled
    current_step INT DEFAULT 0,      -- step đang thực thi
    
    -- Approval
    approved_by BIGINT,              -- user_id who approved
    approved_at TIMESTAMPTZ,
    rejected_reason TEXT,            -- if rejected
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '30 minutes',
    
    CONSTRAINT valid_plan_status CHECK (status IN (
        'draft', 'awaiting_approval', 'approved', 'executing', 
        'completed', 'failed', 'cancelled'
    ))
);

```

### 3.4. `plan_steps` — Từng step trong plan

```sql
CREATE TABLE plan_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID REFERENCES plans(id) ON DELETE CASCADE,
    step_number INT NOT NULL,
    
    -- What to do
    tool_name VARCHAR(50) NOT NULL,      -- "create_text_channel"
    tool_params JSONB NOT NULL DEFAULT '{}',  -- {"name": "vocabulary", "category_id": "..."}
    description TEXT,                    -- "Tạo #vocabulary trong Lessons"
    risk_level VARCHAR(10) NOT NULL DEFAULT 'medium',
    
    -- Execution result
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- pending → executing → completed / failed / skipped
    result JSONB,                        -- tool response data
    error_message TEXT,
    executed_at TIMESTAMPTZ,
    duration_ms INT,
    
    UNIQUE(plan_id, step_number),
    CONSTRAINT valid_step_status CHECK (status IN (
        'pending', 'executing', 'completed', 'failed', 'skipped'
    ))
);

CREATE INDEX idx_plan_steps_plan ON plan_steps(plan_id, step_number);

```

### 3.5. `audit_log` — Mọi tool call (bất kể plan hay fast_track)

```sql
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID REFERENCES requests(id),
    plan_step_id UUID REFERENCES plan_steps(id),  -- NULL nếu fast_track
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    
    -- Action
    tool_name VARCHAR(50) NOT NULL,
    tool_params JSONB NOT NULL,
    risk_level VARCHAR(10) NOT NULL,
    
    -- Result
    success BOOLEAN NOT NULL,
    result_data JSONB,
    error_message TEXT,
    
    -- Context
    approved_by BIGINT,              -- NULL nếu LOW/MEDIUM (auto-exec)
    executed_at TIMESTAMPTZ DEFAULT NOW(),
    duration_ms INT
);

CREATE INDEX idx_audit_guild ON audit_log(guild_id, executed_at DESC);
CREATE INDEX idx_audit_user ON audit_log(user_id, executed_at DESC);

```

### 3.6. `server_snapshots` — Cache server structure (thay thế in-memory)

```sql
CREATE TABLE server_snapshots (
    guild_id BIGINT PRIMARY KEY,
    
    -- Cached data
    categories JSONB DEFAULT '[]',    -- [{id, name, position}]
    channels JSONB DEFAULT '[]',      -- [{id, name, type, category_id}]
    roles JSONB DEFAULT '[]',         -- [{id, name, color, position, permissions}]
    server_info JSONB DEFAULT '{}',   -- {name, icon, member_count, boost_level}
    
    -- Cache control
    snapshot_at TIMESTAMPTZ DEFAULT NOW(),
    stale_after TIMESTAMPTZ DEFAULT NOW() + INTERVAL '60 seconds',
    
    -- Invalidation
    last_modified_by UUID             -- request_id of last write operation
);

```

---

## 4. Request State Machine

```
User gửi message
       │
       ▼
   [received]  ← Request tạo trong DB
       │
       ▼ (Classifier chạy)
   [classified] ← intent + tool_mode saved
       │
       ├── ASSISTANT → QueryService → [completed] (no plan needed)
       │
       ├── FAST_TRACK
       │       │
       │       ├── risk LOW/MED → execute → [completed]
       │       └── risk HIGH → [awaiting_approval] → approve → execute → [completed]
       │
       └── ADMIN_COMPLEX
               │
               ▼ (Planner generates plan)
           [planned]
               │
               ▼ (risk check)
           [awaiting_approval]
               │
               ├── User: "duyệt" → [executing] → step by step → [completed]
               ├── User: "sửa"   → re-plan → [planned] (loop)
               └── User: "hủy"   → [cancelled]

```

**Quan trọng:** Mọi transition được persist vào DB. Nếu bot restart giữa chừng:

- Khi startup, check `requests WHERE status = 'executing'` → resume hoặc report interrupted.
- `plans WHERE status = 'awaiting_approval' AND expires_at > NOW()` → vẫn hiển thị cho user.

---

## 5. Service Layer — Logic Flow

### 5.1. RequestService (Entry Point)

```python
class RequestService:
    """Receives messages, validates, creates DB records, routes."""
    
    async def handle_message(self, guild_id, user_id, message, user_role):
        # 1. Rate limit check
        if await self._is_rate_limited(user_id, guild_id):
            return "⏳ Gửi chậm lại."
        
        # 2. Permission check
        if user_role == "member":
            # Members can only query
            intent = "ASSISTANT"
        else:
            # 3. Classify intent
            intent = await self.classifier.classify(message, user_role)
        
        # 4. Get or create session
        session = await self._get_or_create_session(guild_id, user_id, user_role)
        
        # 5. Check if user is responding to pending approval
        pending = await self._check_pending_approval(session.id, message)
        if pending:
            return await self.executor.handle_approval_response(pending, message)
        
        # 6. Create request record
        request = await self._create_request(session.id, guild_id, user_id, message, intent)
        
        # 7. Route to appropriate service
        match intent:
            case "ASSISTANT":
                return await self.query_service.handle(request)
            case "FAST_TRACK":
                return await self.executor.handle_fast_track(request)
            case "ADMIN_COMPLEX":
                return await self.planner.handle(request)

```

### 5.2. ClassifierService

```python
class ClassifierService:
    """Classify intent — LLM + heuristic fallback."""
    
    async def classify(self, message: str, user_role: str) -> str:
        # Try LLM
        result = await self._llm_classify(message, user_role)
        if result:
            return result
        # Fallback heuristic
        return self._heuristic_classify(message)
    
    def get_tool_mode(self, message: str, intent: str) -> str:
        """Determine which tool subset to show LLM."""
        # Based on keywords in message
        ...

```

### 5.3. PlannerService (ADMIN_COMPLEX)

```python
class PlannerService:
    """Generate execution plan from user request."""
    
    async def handle(self, request: Request) -> str:
        # 1. Get server context from snapshot
        context = await self._get_server_context(request.guild_id)
        
        # 2. Get relevant tools (filtered by mode)
        tools = self._get_tools_for_mode(request.tool_mode)
        
        # 3. Ask LLM to generate plan
        plan_data = await self._generate_plan(request.message, context, tools)
        
        # 4. Store plan + steps in DB
        plan = await self._store_plan(request, plan_data)
        
        # 5. Assess overall risk
        risk = self._assess_risk(plan)
        
        # 6. If HIGH/CRITICAL → await approval
        if risk in ("HIGH", "CRITICAL"):
            await self._set_awaiting_approval(plan)
            return self._format_plan_for_approval(plan)
        
        # 7. If LOW/MEDIUM → auto-execute
        return await self.executor.execute_plan(plan)

```

### 5.4. ExecutorService

```python
class ExecutorService:
    """Execute tool calls — single or plan-based."""
    
    async def handle_fast_track(self, request: Request) -> str:
        # 1. LLM extract tool + params
        tool_call = await self._extract_tool_call(request)
        
        # 2. Risk check
        risk = self._get_risk(tool_call.tool_name)
        if risk in ("HIGH", "CRITICAL"):
            # Store as single-step plan, await approval
            plan = await self._create_single_step_plan(request, tool_call)
            await self._set_awaiting_approval(plan)
            return self._format_confirmation(tool_call)
        
        # 3. Execute directly
        result = await self._execute_tool(request, tool_call)
        return self._format_result(result)
    
    async def execute_plan(self, plan: Plan) -> str:
        """Execute plan step-by-step with progress reporting."""
        plan.status = "executing"
        await self._update_plan(plan)
        
        results = []
        for step in plan.steps:
            step.status = "executing"
            await self._update_step(step)
            
            # Execute via MCP
            result = await self.mcp_client.call_tool(
                step.tool_name, 
                self._inject_guild_id(step.tool_params, plan.guild_id)
            )
            
            if result.success:
                step.status = "completed"
                step.result = result.data
                results.append(f"✅ {step.step_number}/{plan.total_steps}: {step.description}")
            else:
                step.status = "failed"
                step.error_message = result.error
                results.append(f"❌ {step.step_number}/{plan.total_steps}: {step.description} — {result.error}")
                # Stop on failure
                plan.status = "failed"
                await self._update_plan(plan)
                results.append(f"\n⚠️ Dừng ở bước {step.step_number}. Gõ 'tiếp tục' để bỏ qua, 'hủy' để dừng.")
                return "\n".join(results)
            
            await self._update_step(step)
            
            # Invalidate server snapshot cache
            await self._invalidate_snapshot(plan.guild_id)
            
            # Send progress if >5 steps (via callback)
            if plan.total_steps > 5 and step.step_number % 3 == 0:
                await self._send_progress(plan, results[-1])
        
        # All done
        plan.status = "completed"
        await self._update_plan(plan)
        
        # Log to audit
        await self._bulk_audit_log(plan)
        
        results.append(f"\n🎉 Hoàn tất {plan.total_steps}/{plan.total_steps} bước!")
        return "\n".join(results)
    
    async def handle_approval_response(self, plan: Plan, message: str) -> str:
        """Handle user's approval/rejection/modification."""
        action = self._parse_approval_action(message)
        
        match action:
            case "approve":
                plan.status = "approved"
                plan.approved_at = now()
                await self._update_plan(plan)
                return await self.execute_plan(plan)
            
            case "reject":
                plan.status = "cancelled"
                await self._update_plan(plan)
                return "🚫 Đã hủy kế hoạch."
            
            case "modify":
                # Re-plan with user's modification
                modification = self._extract_modification(message)
                return await self.planner.replan(plan, modification)
            
            case "resume":
                # Continue from failed step (skip it)
                return await self._resume_plan(plan)

```

### 5.5. QueryService (ASSISTANT)

```python
class QueryService:
    """Handle read-only queries — may call query tools."""
    
    async def handle(self, request: Request) -> str:
        context = await self._get_server_context(request.guild_id)
        
        # LLM answers with context, optionally calls read-only tools
        response = await self._llm_answer(request.message, context)
        
        request.status = "completed"
        request.response = response
        await self._update_request(request)
        
        return response

```

---

## 6. Server Context (Database-backed)

Thay vì in-memory cache 60s, dùng `server_snapshots` table:

```python
class ServerContextService:
    """Manage cached server structure in database."""
    
    async def get_context(self, guild_id: int) -> str:
        """Get server context — from DB cache or fresh query."""
        snapshot = await self._get_snapshot(guild_id)
        
        if snapshot and snapshot.stale_after > now():
            # Cache valid
            return self._format_context(snapshot)
        
        # Cache miss or stale — refresh from Discord
        fresh_data = await self._fetch_from_discord(guild_id)
        await self._upsert_snapshot(guild_id, fresh_data)
        return self._format_context(fresh_data)
    
    async def invalidate(self, guild_id: int):
        """Called after any write operation."""
        await self._mark_stale(guild_id)
    
    async def _fetch_from_discord(self, guild_id: int) -> dict:
        """Query Discord via MCP read tools."""
        categories = await self.mcp.call_tool("list_categories", {"guild_id": guild_id})
        channels = await self.mcp.call_tool("list_channels", {"guild_id": guild_id})
        roles = await self.mcp.call_tool("list_roles", {"guild_id": guild_id})
        server_info = await self.mcp.call_tool("get_server_info", {"guild_id": guild_id})
        return {
            "categories": categories.data,
            "channels": channels.data,
            "roles": roles.data,
            "server_info": server_info.data,
        }
    
    def _format_context(self, data: dict) -> str:
        """Format for LLM prompt (~200 tokens)."""
        cats = data.get("categories", [])
        chs = data.get("channels", [])
        roles = data.get("roles", [])
        info = data.get("server_info", {})
        
        return f"""Server: {info.get('name', 'Unknown')} ({info.get('member_count', '?')} members)
Categories ({len(cats)}): {', '.join(c['name'] for c in cats[:10])}
Text channels ({len([c for c in chs if c['type']=='text'])}): {', '.join('#'+c['name'] for c in chs if c['type']=='text')[:15]}
Voice channels ({len([c for c in chs if c['type']=='voice'])}): {', '.join(c['name'] for c in chs if c['type']=='voice')[:10]}
Roles ({len(roles)}): {', '.join(r['name'] for r in roles[:10])}"""

```

---

## 7. Approval Flow (Database-backed, robust)

### Tại sao database thay vì in-memory:

| In-memory (cũ) | Database (mới) |
| --- | --- |
| ❌ Mất khi restart | ✅ Persist qua restart |
| ❌ Không audit trail | ✅ Biết ai duyệt, lúc nào |
| ❌ Race condition | ✅ Transaction-safe |
| ❌ Không expire reliable | ✅ `expires_at` column + cleanup job |
| ❌ Không resume được | ✅ Resume từ step cuối thành công |

### Flow:

```
1. PlannerService sinh plan → INSERT plans + plan_steps
2. plans.status = 'awaiting_approval'
3. Bot gửi plan cho user
4. User respond:
   - "duyệt" → UPDATE plans SET status='approved', approved_by=user_id
              → ExecutorService.execute_plan()
   - "hủy"   → UPDATE plans SET status='cancelled'
   - "sửa X" → PlannerService.replan() → new plan version
5. Sau execute:
   - Mỗi step: UPDATE plan_steps SET status, result, executed_at
   - INSERT audit_log cho mỗi tool call
   - Cuối: UPDATE plans SET status='completed'

```

### Resume sau crash:

```python
async def on_startup():
    """Check for interrupted operations after restart."""
    # Find plans that were executing when server died
    interrupted = await db.fetch("""
        SELECT * FROM plans 
        WHERE status = 'executing' 
        ORDER BY created_at
    """)
    
    for plan in interrupted:
        last_completed = await db.fetch("""
            SELECT MAX(step_number) FROM plan_steps
            WHERE plan_id = $1 AND status = 'completed'
        """, plan.id)
        
        # Notify user
        await notify_user(plan.guild_id, plan.user_id,
            f"⚠️ Hệ thống restart giữa chừng. "
            f"Kế hoạch '{plan.description}' đã hoàn thành {last_completed}/{plan.total_steps} bước. "
            f"Gõ 'tiếp tục' để chạy tiếp hoặc 'hủy' để dừng."
        )

```

---

## 8. Security & Permission Model (Database-enforced)

### 8.1. Role-based Access Control:

```python
# Permission matrix — stored in code, enforced in RequestService
PERMISSIONS = {
    "owner":     {"setup", "manage", "moderate", "query", "server_settings", "automod"},
    "admin":     {"setup", "manage", "moderate", "query", "server_settings", "automod"},
    "moderator": {"moderate", "query"},
    "member":    {"query"},
}

# Tool risk → required role
RISK_REQUIRED_ROLE = {
    "LOW":      "member",
    "MEDIUM":   "admin",
    "HIGH":     "admin",      # + HITL approval
    "CRITICAL": "owner",      # + HITL approval
}

```

### 8.2. Rate Limiting (DB-backed):

```sql
CREATE TABLE rate_limits (
    user_id BIGINT NOT NULL,
    guild_id BIGINT NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    request_count INT DEFAULT 1,
    PRIMARY KEY (user_id, guild_id, window_start)
);

-- Check: SELECT request_count FROM rate_limits 
--        WHERE user_id=$1 AND guild_id=$2 
--        AND window_start > NOW() - INTERVAL '1 minute'
-- Limit: 20 requests/minute

```

---

## 9. File Structure (New)

```
AuraFactory/
├── app/
│   ├── main.py                    # FastAPI + Discord bot + startup
│   ├── config.py                  # Settings (env vars)
│   ├── database.py                # PostgreSQL connection pool (asyncpg)
│   │
│   ├── interfaces/                # I/O adapters (thin)
│   │   ├── discord_bot.py         # nextcord bot — on_message → RequestService
│   │   └── api_routes.py          # FastAPI routes — dashboard, approval API
│   │
│   ├── services/                  # Business logic (core)
│   │   ├── request_service.py     # Entry point — validate, route
│   │   ├── classifier_service.py  # Intent classification
│   │   ├── planner_service.py     # Plan generation (ADMIN_COMPLEX)
│   │   ├── executor_service.py    # Tool execution + progress
│   │   ├── query_service.py       # Read-only Q&A
│   │   └── context_service.py     # Server snapshot management
│   │
│   ├── mcp/                       # Tool layer (giữ nguyên)
│   │   ├── client.py              # MCPClient
│   │   ├── protocol.py            # JSON-RPC types
│   │   └── servers/
│   │       └── discord_server.py  # 37 Discord tools
│   │
│   ├── llm/                       # LLM providers
│   │   ├── base.py                # Interface
│   │   ├── gemini.py              # Phase 1
│   │   └── bedrock.py             # Phase 2
│   │
│   └── models/                    # Data models (match DB schema)
│       ├── session.py
│       ├── request.py
│       ├── plan.py
│       └── audit.py
│
├── migrations/                    # SQL migration files
│   ├── 001_create_sessions.sql
│   ├── 002_create_requests.sql
│   ├── 003_create_plans.sql
│   ├── 004_create_audit_log.sql
│   └── 005_create_server_snapshots.sql
│
├── prompts/                       # LLM prompts (English)
│   ├── classifier.md
│   ├── planner.md
│   ├── fast_track.md
│   └── assistant.md
│
├── skills/                        # MCP tool definitions
├── requirements.txt
├── Dockerfile
└── render.yaml

```

---

## 10. Lợi ích so với code cũ

| Vấn đề code cũ | Giải pháp mới |
| --- | --- |
| Bug DI injection (tools = "No tools available") | Service layer đơn giản, inject qua constructor rõ ràng |
| In-memory approval mất khi restart | PostgreSQL — persist, resume |
| System prompt mất sau iteration 0 | Không dùng multi-turn ReAct phức tạp — dùng 1 LLM call sinh full plan, rồi execute plan |
| Classifier safety block → crash | Heuristic fallback + request status tracked → không mất |
| Không biết server có gì | `server_snapshots` table — auto-refresh khi stale |
| Không có audit trail | `audit_log` table — mọi tool call đều ghi |
| Không resume được | State machine + DB → resume từ step cuối |

---

## 11. Key Simplification: Plan-then-Execute thay ReAct

**Code cũ (ReAct loop):** LLM → Tool → Observe → LLM → Tool → ... (khó debug, dễ loop vô hạn)

**Code mới (Plan-then-Execute):**

1. **1 LLM call** sinh toàn bộ plan (list of tool calls + params)
2. **Validate** plan (params hợp lệ, tools tồn tại)
3. **Store** plan vào DB
4. **Approval** (nếu HIGH/CRITICAL)
5. **Execute** step-by-step (deterministic, no LLM needed)

```
                    ┌── LLM ZONE (1-2 calls) ──┐   ┌── DETERMINISTIC ZONE ──┐
User message → Classify → Generate Plan → Validate → Approve → Execute steps
                                                                     │
                                                              No LLM needed
                                                              Just MCP tool calls

```

**Lợi ích:**

- Ít LLM call hơn (2 thay vì 5+) → nhanh hơn + rẻ hơn
- Execution deterministic → dễ debug, dễ resume
- Plan visible cho user trước khi chạy → an toàn hơn
- Không có risk LLM "quên" giữa chừng

---

## 12. Migration Plan

| # | Task | Effort | Depends on |
| --- | --- | --- | --- |
| 1 | Viết migrations SQL (6 tables) | 1h | — |
| 2 | `database.py` (asyncpg pool) | 1h | #1 |
| 3 | `models/` (dataclasses match DB) | 1h | #1 |
| 4 | `classifier_service.py` (giữ logic cũ, bỏ class thừa) | 1h | — |
| 5 | `planner_service.py` (1 LLM call → plan) | 2h | #2, #3 |
| 6 | `executor_service.py` (step-by-step + progress) | 2h | #2, #3 |
| 7 | `context_service.py` (server snapshots) | 1h | #2 |
| 8 | `request_service.py` (routing + approval detection) | 2h | #4, #5, #6 |
| 9 | `discord_bot.py` (thin adapter, on_message) | 1h | #8 |
| 10 | `api_routes.py` (dashboard endpoints) | 1h | #8 |
| 11 | Integration test (1 full scenario) | 2h | All |
| **Total** |  | **~16h** |  |

**Reuse từ code cũ:**

- `mcp/` — toàn bộ (giữ nguyên)
- `llm/gemini.py` — giữ nguyên
- `classifier.py` — logic phân loại (copy vào service mới)
- `skills/` — tool definitions
- `prompts/` — system prompts (có thể tối ưu lại)

