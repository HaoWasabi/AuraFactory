# AuraFactory 

**AI Agent that automates Discord server setup & management via natural language.**

> Built for [Agentic AI Build Week 2026](https://agentic-ai-build-week-2026.devpost.com/) — Track: **Built with AWS**

---

## Demo

```
User: "Tạo cho tui server gaming với 5 kênh voice, role cho mỗi game, và setup automod"

AuraFactory: 📋 Plan (3 steps):
  1. Create category "Gaming" with 5 voice channels
  2. Create roles: Valorant, LoL, CS2, Genshin, Minecraft
  3. Setup AutoMod rule blocking spam links

⚙️ Executing... ✅ Done! 8/8 actions completed.
```

---

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  Discord User (@mention)  │  Web Dashboard  │  REST API        │
└──────────────────────────────────┬─────────────────────────────┘
                                   │
    ┌──────────────────────────────▼──────────────────────────────┐
    │  AWS App Runner (Container)                                 │
    │  ├── L1: Interface Layer (Discord Bot + REST API)           │
    │  ├── L2: Gateway & Safety → Bedrock Guardrails              │
    │  ├── L3: Agent (ReAct Loop) → Amazon Bedrock (Nova)         │
    │  ├── L4: Tools & Skills (MCP Protocol, 80+ tools)           │
    │  ├── L5: Connectors (19 Discord modules)                    │
    │  ├── L6: Memory → DynamoDB (single-table)                   │
    │  └── L7: Observability → CloudWatch + X-Ray                 │
    └─────────────────────────────────────────────────────────────┘
```

### Key Design

| Principle | Implementation |
|-----------|---------------|
| **Spec-driven** | `tools_spec.yaml` (80+ tools) → auto-generates schemas, validation, risk levels |
| **ReAct Loop** | Understand → Act → Observe → Think → Evaluate (bounded: max 5 iterations) |
| **Multi-model routing** | Nova Micro (fast JSON) + Nova Lite (complex reasoning) |
| **Fail-safe** | 4 safety gates, approval for destructive actions, parse-retry on bad LLM output |
| **MCP Protocol** | Standard Model Context Protocol for tool execution |

---

## AWS Services Used

| Service | Role | Why |
|---------|------|-----|
| **Amazon Bedrock** (Nova Micro/Lite) | Core AI reasoning | 75% cheaper than alternatives, native tool calling |
| **Bedrock Guardrails** | Input/output safety | Content filtering, PII detection, denied topics |
| **DynamoDB** | State & memory | Serverless, free tier 25GB, single-table design |
| **App Runner** | Hosting | Auto-scale, deploy from Docker, always-on for bot |
| **CloudWatch + X-Ray** | Observability | Logs, metrics (EMF), distributed tracing |
| **S3** | Knowledge storage | Guild templates, skill files |

---

## Project Structure

```
AuraFactory/
├── app/
│   ├── llm/                 ← LLM providers (Bedrock, Gemini, Ollama)
│   ├── core/                ← Brain (spec_loader, tool_graph, safety, guardrails)
│   ├── services/            ← Business logic (UnifiedAgent, context, auth)
│   ├── connectors/discord/  ← 19 Discord API modules (channels, roles, members...)
│   ├── mcp/                 ← MCP protocol + Discord server
│   ├── interfaces/          ← Entry points (Discord bot, REST API)
│   ├── database_dynamo.py   ← DynamoDB single-table layer
│   └── main.py              ← FastAPI app + lifespan
├── frontend/                ← Web dashboard (HTML/JS/CSS)
├── skills/                  ← Skill .md files for agent context
├── tests/                   ← Test suite (pytest)
├── tools_spec.yaml          ← SOURCE OF TRUTH (all 80+ tools defined here)
├── DEPLOY.md                ← AWS deployment guide (step-by-step)
├── Dockerfile               ← Container build
└── apprunner.yaml           ← App Runner config
```

---

## Quick Start

### Local Development (with AWS services)

```bash
# 1. Clone + install
git clone <repo>
cd AuraFactory
pip install -r requirements.txt

# 2. Configure
cp .env.aws.example .env
# Fill in: DISCORD_TOKEN, AWS credentials

# 3. Run
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Deploy to AWS

See **[DEPLOY.md](DEPLOY.md)** for full step-by-step guide.

```bash
# TL;DR
docker build -t aurafactory .
# Push to ECR → Create App Runner service
# Total cost: ~$12-15 for hackathon week
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LLM_PROVIDER` | ✅ | `bedrock` | LLM backend (`bedrock` / `gemini` / `ollama`) |
| `BEDROCK_MODEL_ID` | ✅ | `amazon.nova-micro-v1:0` | Bedrock model ID |
| `AWS_REGION` | ✅ | `us-east-1` | AWS region |
| `DATABASE_BACKEND` | ✅ | `dynamodb` | Database (`dynamodb` / `postgresql`) |
| `DISCORD_TOKEN` | ✅ | — | Bot token |
| `DISCORD_CLIENT_ID` | ✅ | — | OAuth2 client ID |
| `SECRET_KEY` | ✅ | — | Session signing key |
| `BEDROCK_GUARDRAIL_ID` | ⚡ | — | Guardrail ID (optional) |
| `GUILD_LOCK_MODE` | — | `open` | `open` or `whitelist` |

---

## Safety & Security

| Layer | Mechanism |
|-------|-----------|
| **Input Guardrail** | Regex injection detection (local, ~0ms) |
| **Bedrock Guardrails** | Managed content filtering, PII, denied topics (~50ms) |
| **Approval Gate** | HIGH-risk actions (delete/ban/kick) require user confirmation |
| **Guild Lock** | Whitelist mode restricts to authorized servers |
| **Token Budget** | Daily per-guild cap prevents runaway costs |
| **Rate Limiter** | 0.5s delay + burst=5 to respect Discord API limits |
| **Audit Logger** | Every tool execution logged (DynamoDB, 90-day TTL) |

---

## Cost Estimate

| Scenario | Monthly Cost |
|----------|-------------|
| Hackathon (7 days, low traffic) | **~$12-15 total** |
| Production (500 req/day) | ~$20-30/month |
| Development (local + remote AWS) | **~$0.10-0.30/day** |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11 |
| Web Framework | FastAPI + Uvicorn |
| Discord | Nextcord |
| AI/LLM | Amazon Bedrock (Nova Micro/Lite) |
| Database | DynamoDB (single-table) |
| Safety | Bedrock Guardrails + custom regex |
| Observability | CloudWatch EMF + X-Ray |
| Hosting | AWS App Runner (Docker) |
| Tool Protocol | MCP (Model Context Protocol) |

---

## License

MIT
