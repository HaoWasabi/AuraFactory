# AuraFactory — Production Fix Spec v1

> Master spec for ALL production hardening changes.
> Every file modification MUST reference this spec.

---

## Principles

1. **Spec-driven**: This document is the single source of truth for what changes.
2. **Zero dead code**: Remove unused classes, imports, stale docs.
3. **Consistency**: All components follow same patterns (error handling, logging, config).
4. **Fail-fast**: Missing required config = crash at startup, not silent fallback.
5. **Defense in depth**: Multiple layers of protection (input → processing → output).

---

## CHANGES MANIFEST

### 1. config.py — Security Hardening

```
REMOVE: SECRET_KEY default fallback 'dev-secret-key-change-in-production'
ADD: Fail-fast validation for required env vars (DISCORD_TOKEN, SECRET_KEY, DATABASE_URL)
FIX: CORS default from ["*"] → [] (empty = reject all, must be explicitly configured)
ADD: MAX_MESSAGE_LENGTH = 2000
ADD: DAILY_TOKEN_BUDGET = 800000
ADD: PER_REQUEST_TOKEN_LIMIT = 10000
ADD: GUILD_LOCK_MODE default → "whitelist" (production safe)
REMOVE: Redundant lowercase property aliases (use UPPER directly)
```

### 2. database.py — Reliability

```
FIX: SSL — enable proper verification (remove CERT_NONE)
ADD: Statement timeout (30s default)
ADD: Connection health check via pool config
ADD: Advisory lock for migrations (prevent concurrent runs)
KEEP: Retry logic already in main.py lifespan (5 attempts with backoff)
```

### 3. Dockerfile — Security

```
ADD: Non-root user (appuser)
ADD: .dockerignore reference
FIX: Multi-stage build not needed (slim is fine), but add proper USER directive
```

### 4. main.py — Gateway Hardening

```
ADD: SecurityHeadersMiddleware (CSP, HSTS, X-Frame-Options, X-Content-Type-Options)
FIX: Health check → include DB connectivity + uptime + active sessions
ADD: Startup time tracking on app.state
REMOVE: Emoji from log messages (not structured-friendly)
ADD: Structured JSON logging formatter
ADD: Request ID middleware (X-Request-ID header)
```

### 5. app/core/safety.py — Guardrails

```
ADD: InputGuardrail class (prompt injection detection)
REMOVE: RateLimiter class (dead code — replaced by RateLimitMiddleware in middleware.py)
KEEP: ApprovalGate, GuildLock, AuditLogger, ConversationMemory
ADD: OutputValidator class (validate LLM JSON before execution)
```

### 6. app/core/middleware.py — Pipeline Enhancement

```
ADD: TokenBudgetMiddleware (check daily budget before execution)
ADD: InputValidationMiddleware (message length + basic sanitization)
ADD: CircuitBreakerMiddleware (for Discord API failures)
ADD: MetricsMiddleware (request count, latency histogram, error rate)
KEEP: All existing middlewares unchanged
```

### 7. unified_agent.py — Agent Hardening

```
ADD: Input length check at entry point (MAX_MESSAGE_LENGTH)
ADD: Token budget check before LLM call
ADD: Idempotency key generation for create_* operations
ADD: Context window estimation (truncate if too large)
FIX: Use InputGuardrail before processing
```

### 8. app/core/observability.py — NEW FILE

```
CREATE: Structured JSON log formatter
CREATE: Prometheus metrics (counters, histograms, gauges)
CREATE: /metrics endpoint handler
CREATE: Request tracing context (request_id propagation)
```

### 9. requirements.txt — Dependencies

```
ADD: prometheus-client>=0.20.0
ADD: python-json-logger>=2.0.0
REMOVE: Nothing (all current deps are used)
```

### 10. docker-compose.yml — Security

```
FIX: Remove hardcoded POSTGRES_PASSWORD (use .env)
ADD: Network isolation (internal network for db)
ADD: Resource limits (memory, CPU)
```

### 11. Clean-up

```
REMOVE: docs/AGENTIC_ARCHITECTURE_V5.md (stale, replaced by v6 in unified_agent.py)
UPDATE: ARCHITECTURE.md — add version note referencing this spec
```

---

## Implementation Order

1. requirements.txt (dependencies first)
2. config.py (foundation)
3. app/core/observability.py (new — needed by others)
4. database.py
5. app/core/safety.py (add InputGuardrail, remove dead code)
6. app/core/middleware.py (add new middlewares)
7. unified_agent.py (integrate guardrails + budget)
8. main.py (integrate all)
9. Dockerfile + docker-compose.yml
10. Clean-up (remove stale files)

---

## Success Criteria

- [ ] No hardcoded secrets or unsafe defaults
- [ ] Structured JSON logs on all requests
- [ ] Prometheus metrics exposed at /metrics
- [ ] Input validation (length, injection detection) on all entry points
- [ ] Token budget enforced per-guild per-day
- [ ] Circuit breaker prevents retry storms
- [ ] Health check reports dependency status
- [ ] Docker runs as non-root
- [ ] All dead code removed
- [ ] Zero new warnings on startup
