# AuraFactory — Data Subsystem Design v2

> **Architecture**: PostgreSQL (durable) + Redis (hot cache) + SQLite+FTS5 (knowledge) **Goal**: Mỗi store làm đúng việc nó giỏi nhất. Zero overlap, clear ownership.

---

## 1. Design Principles

| # | Principle | Rationale |
| --- | --- | --- |
| 1 | **Single Writer per entity** | Mỗi data entity chỉ được write bởi 1 service → no conflict |
| 2 | **Right store for right job** | Postgres = durable ACID, Redis = ephemeral hot, SQLite = local search |
| 3 | **Fail-open where possible** | Redis down → fallback in-memory. SQLite down → skip knowledge. Only Postgres is critical. |
| 4 | **Guild isolation** | Mỗi guild có SQLite file riêng → easy cleanup, no cross-contamination |
| 5 | **Schema-first** | All schemas defined upfront, migrations tracked |

---

## 2. Store Responsibilities

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         DATA FLOW                                        │
│                                                                         │
│  User Request ──→ Redis (session lookup) ──→ Agent Loop                 │
│                                              │                          │
│                       ┌──────────────────────┼──────────────────┐       │
│                       │                      │                  │       │
│                       ▼                      ▼                  ▼       │
│              Redis (context cache)    SQLite (knowledge)   Postgres     │
│              • server_snapshot        • conversation log   • audit_log  │
│              • rate_limit             • server rules       • users      │
│              • guild_lock             • pinned content     • installs   │
│              • active_sessions        • user preferences   • billing    │
│                                       • FTS5 index                      │
└─────────────────────────────────────────────────────────────────────────┘

```

---

## 3. Store 1 — PostgreSQL (Durable / System of Record)

### What belongs here

- Data that MUST survive restarts and crashes
- Data needed for billing, compliance, legal
- Cross-guild aggregations (analytics)

### Schema (simplified from current — drop cache tables)

```sql
-- ══════════════════════════════════════════════
-- IDENTITY & AUTH
-- ══════════════════════════════════════════════

CREATE TABLE users (
    discord_user_id  BIGINT PRIMARY KEY,
    username         VARCHAR(100),
    avatar_hash      VARCHAR(100),
    access_token_enc TEXT,
    refresh_token_enc TEXT,
    token_expires_at TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    last_login_at    TIMESTAMPTZ
);

CREATE TABLE bot_installs (
    guild_id      BIGINT PRIMARY KEY,
    guild_name    VARCHAR(100),
    installed_by  BIGINT REFERENCES users(discord_user_id),
    installed_at  TIMESTAMPTZ DEFAULT NOW(),
    is_active     BOOLEAN DEFAULT TRUE,
    config_json   JSONB DEFAULT '{}'  -- per-guild settings (language, features on/off)
);

-- ══════════════════════════════════════════════
-- AUDIT & COMPLIANCE (append-only, never update)
-- ══════════════════════════════════════════════

CREATE TABLE audit_log (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    guild_id      BIGINT NOT NULL,
    user_id       BIGINT NOT NULL,
    tool_name     VARCHAR(80) NOT NULL,
    tool_params   JSONB NOT NULL,
    risk_level    VARCHAR(10) NOT NULL,
    success       BOOLEAN NOT NULL,
    result_summary TEXT,          -- short outcome (not full payload)
    error_message TEXT,
    duration_ms   INT,
    executed_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_audit_guild_time ON audit_log(guild_id, executed_at DESC);
CREATE INDEX idx_audit_user_time ON audit_log(user_id, executed_at DESC);

-- ══════════════════════════════════════════════
-- USAGE & BILLING
-- ══════════════════════════════════════════════

CREATE TABLE usage_daily (
    guild_id       BIGINT NOT NULL,
    date           DATE NOT NULL,
    requests_count INT DEFAULT 0,
    tokens_in      INT DEFAULT 0,
    tokens_out     INT DEFAULT 0,
    tools_executed INT DEFAULT 0,
    PRIMARY KEY (guild_id, date)
);

```

### What was REMOVED from Postgres

| Old Table | New Location | Reason |
| --- | --- | --- |
| `sessions` | Redis | Ephemeral, TTL-based, needs sub-ms lookup |
| `server_snapshots` | Redis | Cache with 60s TTL — Redis's native job |
| `rate_limits` | Redis | Counter with sliding window — Redis INCR |
| `guild_admin_cache` | Redis | TTL cache of permissions |
| `requests` | Dropped (already in-memory) | RequestLifecycle FSM handles this |
| `plans` / `plan_steps` | Dropped (already in-memory) | v1 legacy, never used by v3.1 |
| `messages` | SQLite (per-guild) | Needs FTS, per-guild isolation |

---

## 4. Store 2 — Redis (Hot Cache / Ephemeral State)

### Why Redis (not just in-memory dict)

- **Survives process restart** (bot redeploy doesn't lose sessions)
- **TTL is native** — no manual expiry sweep
- **Atomic operations** — INCR for rate-limit, SETNX for locks
- **Pub/Sub** — future: multi-process sync
- **Bounded memory** — maxmemory + eviction policy

### Key Schema

```
Namespace pattern: aura:{guild_id}:{entity}:{sub_key}

┌─────────────────────────────────────────────────────────────────────┐
│ KEY                              │ TYPE    │ TTL    │ PURPOSE        │
├──────────────────────────────────┼─────────┼────────┼────────────────┤
│ aura:{gid}:session:{uid}        │ HASH    │ 30min  │ Active session │
│ aura:{gid}:snapshot             │ HASH    │ 60s    │ Server context │
│ aura:{gid}:lock                 │ STRING  │ 30s    │ Guild exec lock│
│ aura:{gid}:ratelimit:{uid}      │ STRING  │ 60s    │ Request counter│
│ aura:{gid}:admin_perms:{uid}    │ STRING  │ 5min   │ Permission bits│
│ aura:{gid}:approval:{req_id}    │ HASH    │ 5min   │ Pending confirm│
└─────────────────────────────────────────────────────────────────────┘

```

### Detail per key

Session (`HASH`, TTL 30min)

```redis
HSET aura:123:session:456
    user_role   "admin"
    source      "discord"
    channel_id  "789"
    history     "[{role:'user',content:'...'}, ...]"  -- JSON string, last N turns
    created_at  "2024-01-01T00:00:00Z"

EXPIRE aura:123:session:456 1800

```

**Access pattern**: Read on every request, write after every turn. **Eviction**: TTL auto-expire. Conversation history also saved to SQLite for persistence.

Server Snapshot (`HASH`, TTL 60s)

```redis
HSET aura:123:snapshot
    categories  "[...]"   -- JSON
    channels    "[...]"
    roles       "[...]"
    server_info "{...}"
    fetched_at  "2024-..."

EXPIRE aura:123:snapshot 60

```

**Access pattern**: Read every request. Write on cache-miss (fetch from Discord API). **Miss strategy**: On MISS → fetch from Discord → SET + TTL 60s.

Rate Limit (`STRING` + INCR, TTL 60s)

```redis
-- Sliding window counter
INCR aura:123:ratelimit:456
EXPIRE aura:123:ratelimit:456 60  -- only on first INCR (NX)

-- Check: if value > burst_limit → reject

```

Guild Lock (`STRING` + SETNX, TTL 30s)

```redis
SET aura:123:lock "request_abc" NX EX 30
-- Returns OK if acquired, nil if locked
-- Auto-releases after 30s (crash safety)

```

Approval (`HASH`, TTL 5min)

```redis
HSET aura:123:approval:req_abc
    tools       "[{name:'delete_channel', params:{...}}]"
    risk_level  "high"
    message_id  "discord_msg_id_for_reaction"
    user_id     "456"

EXPIRE aura:123:approval:req_abc 300

```

### Redis Configuration

```
# redis.conf (or Render Redis addon)
maxmemory 50mb
maxmemory-policy allkeys-lru
save ""                          # No RDB persistence (we treat Redis as cache)
appendonly no                    # No AOF — data is reconstructible

```

**Fail-open**: If Redis is unreachable:

- Session → create new (stateless mode, no history)
- Snapshot → fetch from Discord directly (slower but works)
- Rate-limit → skip (allow request through)
- Lock → in-memory fallback dict

---

## 5. Store 3 — SQLite + FTS5 (Knowledge Layer)

### Why SQLite

- **Zero infrastructure** — embedded, no server process
- **FTS5** — full-text search built-in, fast, battle-tested
- **Per-guild file** — `data/guilds/{guild_id}.db` → easy backup, isolation, cleanup
- **WAL mode** — concurrent reads while writing
- **Phase 2 upgrade path** — when you need vector search, add `sqlite-vec` extension or migrate to Qdrant

### File Layout

```
data/
└── guilds/
    ├── 123456789.db      ← Guild A's knowledge
    ├── 987654321.db      ← Guild B's knowledge
    └── ...

```

### Schema (per-guild SQLite file)

```sql
-- ══════════════════════════════════════════════
-- PRAGMA (set on connection open)
-- ══════════════════════════════════════════════
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

-- ══════════════════════════════════════════════
-- CONVERSATION HISTORY (durable, searchable)
-- ══════════════════════════════════════════════

CREATE TABLE conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,          -- links to Redis session
    user_id     INTEGER NOT NULL,
    role        TEXT NOT NULL,          -- 'user' | 'assistant' | 'system'
    content     TEXT NOT NULL,
    tool_calls  TEXT,                   -- JSON array of tool calls (if assistant)
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_conv_session ON conversations(session_id, created_at);
CREATE INDEX idx_conv_user ON conversations(user_id, created_at DESC);

-- FTS5 virtual table for conversation search
CREATE VIRTUAL TABLE conversations_fts USING fts5(
    content,
    content=conversations,
    content_rowid=id,
    tokenize='unicode61 remove_diacritics 2'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER conv_ai AFTER INSERT ON conversations BEGIN
    INSERT INTO conversations_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER conv_ad AFTER DELETE ON conversations BEGIN
    INSERT INTO conversations_fts(conversations_fts, rowid, content)
        VALUES('delete', old.id, old.content);
END;

-- ══════════════════════════════════════════════
-- SERVER KNOWLEDGE (persistent, searchable)
-- ══════════════════════════════════════════════

CREATE TABLE knowledge (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category    TEXT NOT NULL,          -- 'rule' | 'announcement' | 'pin' | 'faq' | 'event' | 'custom'
    source      TEXT NOT NULL,          -- 'pinned_message' | 'channel_topic' | 'admin_input' | 'auto_detected'
    source_id   TEXT,                   -- Discord message ID or channel ID (for dedup)
    title       TEXT,
    content     TEXT NOT NULL,
    channel_id  INTEGER,               -- Which channel this came from
    author_id   INTEGER,               -- Who wrote/pinned it
    priority    INTEGER DEFAULT 0,     -- Higher = more important (rules > random pins)
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now')),
    expires_at  TEXT                    -- NULL = never expires
);
CREATE INDEX idx_knowledge_category ON knowledge(category, is_active);
CREATE UNIQUE INDEX idx_knowledge_source_dedup ON knowledge(source, source_id)
    WHERE source_id IS NOT NULL;

-- FTS5 for knowledge search (Assistant Mode Q&A)
CREATE VIRTUAL TABLE knowledge_fts USING fts5(
    title,
    content,
    category,
    content=knowledge,
    content_rowid=id,
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER knowledge_ai AFTER INSERT ON knowledge BEGIN
    INSERT INTO knowledge_fts(rowid, title, content, category)
        VALUES (new.id, new.title, new.content, new.category);
END;
CREATE TRIGGER knowledge_ad AFTER DELETE ON knowledge BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, title, content, category)
        VALUES('delete', old.id, old.title, old.content, old.category);
END;
CREATE TRIGGER knowledge_au AFTER UPDATE ON knowledge BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, title, content, category)
        VALUES('delete', old.id, old.title, old.content, old.category);
    INSERT INTO knowledge_fts(rowid, title, content, category)
        VALUES (new.id, new.title, new.content, new.category);
END;

-- ══════════════════════════════════════════════
-- USER PREFERENCES (per-guild per-user)
-- ══════════════════════════════════════════════

CREATE TABLE preferences (
    user_id     INTEGER NOT NULL,
    key         TEXT NOT NULL,          -- 'language' | 'skip_confirm' | 'default_channel_type' | ...
    value       TEXT NOT NULL,
    updated_at  TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, key)
);

-- ══════════════════════════════════════════════
-- METADATA (schema version tracking)
-- ══════════════════════════════════════════════

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
INSERT INTO meta(key, value) VALUES ('schema_version', '1');
INSERT INTO meta(key, value) VALUES ('created_at', datetime('now'));

```

### Knowledge Ingestion Pipeline

```
Discord Events → Ingest → SQLite Knowledge Table

Sources:
  1. Pinned messages   → on pin_add event / periodic scan
  2. Channel topics    → on channel_update event
  3. Server rules      → from guild.features (community servers)
  4. Announcements     → messages in announcement channels
  5. Admin-defined     → admin says "remember this: ..."

```

| Source | Trigger | Category | Priority |
| --- | --- | --- | --- |
| Server rules (community) | `guild_update` event | `rule` | 10 |
| Pinned message | `message_pin` event | `pin` | 5 |
| Channel topic | `channel_update` event | `faq` | 3 |
| Announcement channel msg | `message_create` (in announcement ch) | `announcement` | 7 |
| Admin explicit "remember" | User command | `custom` | 8 |

### Query Examples

```sql
-- Assistant Mode: User asks "what are the server rules?"
SELECT id, title, content, category
FROM knowledge_fts
WHERE knowledge_fts MATCH 'rules OR server rules'
ORDER BY rank
LIMIT 5;

-- Search conversation history
SELECT c.role, c.content, c.created_at
FROM conversations_fts f
JOIN conversations c ON c.id = f.rowid
WHERE conversations_fts MATCH 'channel setup'
ORDER BY c.created_at DESC
LIMIT 10;

-- Get user preference
SELECT value FROM preferences WHERE user_id = 456 AND key = 'language';

```

---

## 6. Access Layer — Repository Pattern

### Code Structure

```
app/
└── data/
    ├── __init__.py
    ├── postgres.py          ← PostgresRepo (auth, audit, billing)
    ├── redis_cache.py       ← RedisCache (sessions, snapshots, locks)
    ├── knowledge_store.py   ← KnowledgeStore (per-guild SQLite)
    └── data_manager.py      ← DataManager facade (single entry point)

```

### DataManager (Facade)

```python
class DataManager:
    """Single entry point for all data operations.
    
    Services should NEVER talk to stores directly.
    This facade routes to the correct store and handles fail-open.
    """
    
    def __init__(self, postgres: PostgresRepo, redis: RedisCache, knowledge_dir: str):
        self.pg = postgres
        self.redis = redis
        self._knowledge_dir = knowledge_dir
        self._stores: dict[int, KnowledgeStore] = {}  # guild_id → store
    
    # ── Session ──
    async def get_session(self, guild_id: int, user_id: int) -> Session | None:
        return await self.redis.get_session(guild_id, user_id)
    
    async def save_session(self, session: Session) -> None:
        await self.redis.save_session(session)
        # Also persist last N messages to SQLite (durable backup)
        store = self._get_knowledge_store(session.guild_id)
        await store.append_conversation(session)
    
    # ── Server Context ──
    async def get_server_context(self, guild_id: int) -> ServerContext | None:
        return await self.redis.get_snapshot(guild_id)
    
    async def cache_server_context(self, guild_id: int, ctx: ServerContext) -> None:
        await self.redis.set_snapshot(guild_id, ctx, ttl=60)
    
    # ── Knowledge ──
    async def search_knowledge(self, guild_id: int, query: str, limit: int = 5) -> list[KnowledgeItem]:
        store = self._get_knowledge_store(guild_id)
        return await store.search(query, limit)
    
    async def ingest_knowledge(self, guild_id: int, item: KnowledgeItem) -> None:
        store = self._get_knowledge_store(guild_id)
        await store.upsert(item)
    
    # ── Audit ──
    async def log_audit(self, entry: AuditEntry) -> None:
        await self.pg.insert_audit(entry)
    
    # ── Rate Limit ──
    async def check_rate_limit(self, guild_id: int, user_id: int, burst: int) -> bool:
        return await self.redis.check_rate_limit(guild_id, user_id, burst)
    
    # ── Guild Lock ──
    async def acquire_lock(self, guild_id: int, request_id: str, ttl: int = 30) -> bool:
        return await self.redis.acquire_lock(guild_id, request_id, ttl)
    
    async def release_lock(self, guild_id: int, request_id: str) -> None:
        await self.redis.release_lock(guild_id, request_id)
    
    # ── Private ──
    def _get_knowledge_store(self, guild_id: int) -> KnowledgeStore:
        if guild_id not in self._stores:
            self._stores[guild_id] = KnowledgeStore(
                db_path=f"{self._knowledge_dir}/{guild_id}.db"
            )
        return self._stores[guild_id]

```

---

## 7. Migration Plan (Current → New)

### Phase 1: Add Redis + refactor (no data loss)

```
Step 1: Add redis dependency (aioredis / redis-py async)
Step 2: Create app/data/redis_cache.py
Step 3: Migrate session logic:
        - ContextService → uses RedisCache.get_snapshot() instead of DB query
        - Session management → Redis HASH instead of Postgres sessions table
Step 4: Migrate safety.py:
        - RateLimiter → Redis INCR
        - GuildLock → Redis SETNX
Step 5: Drop Postgres tables: sessions, server_snapshots, rate_limits, guild_admin_cache

```

### Phase 2: Add SQLite Knowledge Layer

```
Step 1: Create app/data/knowledge_store.py
Step 2: Create data/guilds/ directory
Step 3: Implement KnowledgeIngester service (Discord event → SQLite)
Step 4: Wire into unified_agent.py: before LLM call, search knowledge
Step 5: Add conversation persistence (Redis session → SQLite on each turn)

```

### Phase 3: Wire DataManager

```
Step 1: Create app/data/data_manager.py (facade)
Step 2: Refactor unified_agent.py to use DataManager (not direct DB)
Step 3: Refactor context_service.py → thin wrapper over DataManager
Step 4: Remove old database.py references from services
Step 5: Update tests

```

---

## 8. Deployment Topology

### Render.com (Current hosting)

```
┌─────────────────────────────────────────────┐
│  Render Web Service (Docker)                │
│  ┌───────────────────────────────────────┐  │
│  │  AuraFactory Bot Process              │  │
│  │  • FastAPI + Nextcord                 │  │
│  │  • SQLite files in /data/guilds/      │  │
│  │    (persistent disk)                  │  │
│  └───────────────────────────────────────┘  │
│                │              │              │
│                ▼              ▼              │
│  ┌─────────────────┐  ┌──────────────┐     │
│  │ Render Postgres │  │ Render Redis │     │
│  │  (Free tier)    │  │ (Free tier)  │     │
│  │  • Auth/Audit   │  │ • 25MB       │     │
│  │  • Billing      │  │ • Sessions   │     │
│  └─────────────────┘  │ • Cache      │     │
│                        └──────────────┘     │
└─────────────────────────────────────────────┘

SQLite storage:
  Render Persistent Disk (1GB free) mounted at /data/
  Or: Render's /opt/render/ ephemeral + periodic backup to S3

```

### Resource Estimation

| Store | Free Tier Limit | AuraFactory Usage (10 guilds) |
| --- | --- | --- |
| Postgres | 256MB, 90-day expiry | ~5MB (audit + users) ✅ |
| Redis | 25MB | ~2MB (sessions + cache) ✅ |
| SQLite | Disk space | ~50MB (conversations + knowledge) ✅ |

---

## 9. Fail-Open Strategy

```python
class RedisCache:
    async def get_snapshot(self, guild_id: int) -> ServerContext | None:
        try:
            data = await self._redis.hgetall(f"aura:{guild_id}:snapshot")
            return ServerContext.from_redis(data) if data else None
        except (ConnectionError, TimeoutError):
            logger.warning("Redis unavailable, returning None (will fetch from Discord)")
            return None  # Caller fetches from Discord API directly

```

| Failure | Behavior | User Impact |
| --- | --- | --- |
| Redis down | Fallback to in-memory dict (no persistence) | Slightly slower, no cross-restart memory |
| SQLite corrupt | Auto-recreate empty DB for that guild | Lose knowledge, conversations still in Redis |
| Postgres down | Bot still runs, skip audit logging | No audit trail (logged to file as backup) |
| All stores down | Bot responds "I'm having storage issues, please retry" | Graceful degradation |

---

## 10. Phase 2 Upgrade Path (When You Scale)

| Component | Phase 1 (Now) | Phase 2 (Scale) |
| --- | --- | --- |
| Full-text search | SQLite FTS5 | Keep (fast enough to 100K docs) |
| Vector/semantic search | Not needed yet | Add `sqlite-vec` OR migrate to Qdrant |
| Redis | Render Redis 25MB | Upstash Redis (serverless) or ElastiCache |
| Postgres | Render free | Supabase or AWS RDS |
| SQLite backup | Manual / cron to S3 | Litestream (real-time replication to S3) |
| Multi-process | Single process | Redis Pub/Sub for event sync |

### Adding Vector Search (when needed)

```python
# Option A: sqlite-vec extension (zero new infra)
# pip install sqlite-vec
import sqlite_vec

conn.enable_load_extension(True)
sqlite_vec.load(conn)

# CREATE VIRTUAL TABLE knowledge_vec USING vec0(embedding float[384]);
# INSERT INTO knowledge_vec(rowid, embedding) VALUES (?, ?);
# SELECT rowid, distance FROM knowledge_vec WHERE embedding MATCH ? LIMIT 5;

# Option B: Qdrant (separate service, more powerful)
# Deploy when you need: multi-tenant, >100K embeddings, or hybrid search

```

---

## 11. Summary — What Changed

| Before (v1) | After (v2) |
| --- | --- |
| Postgres does everything | Postgres = durable record only |
| `sessions` table with JSONB blob | Redis HASH with TTL |
| `server_snapshots` with SQL TTL hack | Redis HASH with native EXPIRE |
| `rate_limits` table with window query | Redis INCR + EXPIRE |
| No conversation search | SQLite FTS5 full-text search |
| No knowledge store | SQLite per-guild with ingestion pipeline |
| No user preferences persistence | SQLite `preferences` table |
| 10+ Postgres tables | 3 Postgres tables + Redis keys + SQLite |
| Single point of failure | Fail-open design |

