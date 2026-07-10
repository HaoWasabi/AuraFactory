# AuraFactory — Agentic Architecture v5 (Closed-Loop)

## Mục tiêu thiết kế

1. **Zero dead-end**: Mọi nhánh trong flow đều dẫn tới kết quả (success/ask user/report failure) — KHÔNG BAO GIỜ dừng giữa chừng.
2. **Goal-aware**: Agent luôn biết mục tiêu GỐC, dù conversation trải qua nhiều turn ("ok", "yes", "đồng ý").
3. **Dependency-resolved**: Output step N được inject vào step N+1 (created IDs flow forward).
4. **Single LLM contract**: 1 system prompt, 1 LLM call pattern — LLM quyết định TẤT CẢ (classify/plan/execute/reflect) trong mỗi call.
5. **Bounded**: Max iterations + token budget → agent không loop forever.

---

## Core Loop (State Machine)

```
                    ┌─────────────────────────────────┐
                    │           IDLE                    │
                    └────────────────┬────────────────┘
                                    │ user message arrives
                                    ▼
                    ┌─────────────────────────────────┐
                    │      UNDERSTAND (1 LLM call)     │
                    │                                   │
                    │  Input: message + history +       │
                    │         server_state + skills     │
                    │                                   │
                    │  Output (LLM decides ONE of):     │
                    │    A) text_response → RESPOND     │
                    │    B) tool_calls → ACT            │
                    │    C) clarify_question → ASK      │
                    └─────┬──────────┬──────────┬──────┘
                          │          │          │
                   ┌──────▼──┐  ┌───▼────┐ ┌───▼───┐
                   │ RESPOND  │  │  ACT   │ │  ASK  │
                   │(terminal)│  │(loop)  │ │(wait) │
                   └──────────┘  └───┬────┘ └───┬───┘
                                     │          │
                                     ▼          │ user replies
                    ┌─────────────────────────┐ │
                    │      EXECUTE LOOP        │◄┘
                    │                           │
                    │  FOR each tool call:      │
                    │    ├─ is HIGH RISK?       │
                    │    │   YES → PAUSE (ask)  │
                    │    │   NO  → execute      │
                    │    ├─ observe result      │
                    │    └─ inject output into  │
                    │       next call's context │
                    │                           │
                    │  AFTER batch complete:    │
                    │    → EVALUATE             │
                    └──────────────┬────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────────┐
                    │         EVALUATE (1 LLM call)    │
                    │                                   │
                    │  Input: goal + all results +      │
                    │         fresh server_state        │
                    │                                   │
                    │  Output (LLM decides ONE of):     │
                    │    A) DONE → RESPOND              │
                    │    B) MORE_TOOLS → back to ACT    │
                    │    C) NEED_INFO → ASK             │
                    │    D) FAILED → RESPOND (explain)  │
                    └──────────────────────────────────┘

```

---

## Key Design Decisions

### 1. Goal Persistence (giải quyết "ok" problem)

```python
# Mọi conversation có 1 "effective_goal" được resolve TRƯỚC LLM call:
effective_goal = resolve_goal(current_message, history)
# Rule: nếu message là confirmation ("ok","yes","đồng ý") 
#   → goal = last substantive user message from history
# Else: goal = current message

```

Goal này được truyền vào MỌI LLM call (UNDERSTAND + EVALUATE) để agent luôn biết nó đang làm gì.

### 2. Single Prompt Pattern (thay vì 4 prompt riêng)

Thay vì UNIFIED_SYSTEM_PROMPT + REFLECT_PROMPT + ASSEMBLE_PROMPT + PLANNER_PROMPT (4 prompts, 4 LLM personalities khác nhau), dùng **1 system prompt duy nhất** với output format linh hoạt:

```
System prompt bảo LLM:
  "Bạn là AuraFactory. Mỗi turn bạn PHẢI output 1 trong 3 format:
   
   FORMAT A — Direct response (no tools needed):
   {"action": "respond", "message": "..."}
   
   FORMAT B — Need to call tools:
   {"action": "execute", "plan_summary": "...", "tool_calls": [...]}
   
   FORMAT C — Need user clarification:
   {"action": "clarify", "question": "..."}"

```

**Ưu điểm**: LLM tự classify intent + tự quyết respond/execute/ask — KHÔNG CẦN bước classify riêng.

### 3. Execution: Sequential with Forward Context

```python
results = []
for tool_call in plan.tool_calls:
    # Inject previous results into params (resolve dependencies)
    params = resolve_dependencies(tool_call.params, results)
    
    # Execute
    result = await execute_tool(tool_call.name, params)
    results.append(result)
    
    # KHÔNG dừng nếu 1 tool fail — continue, để EVALUATE quyết định

```

**Critical**: Created IDs flow forward. Example:

```
Step 1: create_category(name="GAMING") → result: {id: "123456"}
Step 2: create_channel(name="general", category_id="$step1.id") 
  → resolve: category_id = "123456" (from step 1)

```

### 4. Evaluate = Reflect + Assemble combined

Thay vì 2 LLM calls riêng (reflect + assemble), gộp thành 1:

```
Input cho EVALUATE:
  - effective_goal
  - All results (success + failures)
  - Fresh server state (after execution)

Output format:
  A) {"action": "done", "response": "Đã tạo xong! 🎉 ..."}
  B) {"action": "continue", "tool_calls": [...], "reason": "..."}
  C) {"action": "ask_user", "question": "..."}
  D) {"action": "failed", "response": "Xin lỗi, không thể ... vì ..."}

```

**1 call = reflect + assemble + decide next** — saves 1 LLM call per iteration.

### 5. Approval Gate (unchanged logic, better placement)

```
TRƯỚC mỗi batch execute:
  high_risk = [t for t in tool_calls if t.risk >= HIGH]
  if high_risk:
    → PAUSE: show description, wait user "yes"
    → Store: {goal, pending_tools, results_so_far}
    → On "yes": resume execute loop
    → On "no": cancel → respond "Cancelled"

```

### 6. Max Iterations + Budget

```python
MAX_ITERATIONS = 5  # Total loop passes
MAX_TOOL_CALLS = 20  # Total tools across all iterations
MAX_LLM_CALLS = 8   # Total LLM calls (UNDERSTAND + EVALUATE passes)

```

If any limit hit → force RESPOND with partial results summary.

---

## LLM Calls Summary (optimal)

| Scenario | LLM calls | Tools |
| --- | --- | --- |
| Simple query ("list channels") | 1 (UNDERSTAND → respond) | 1 |
| Simple action ("create role VIP") | 2 (UNDERSTAND → execute → EVALUATE → done) | 1 |
| Complex multi-step ("setup server") | 3-4 (UNDERSTAND → execute 5 → EVALUATE → execute 5 more → EVALUATE → done) | 10-15 |
| Failure + retry | 3-5 (+ 1 EVALUATE that triggers retry) | varies |
| Clarify needed | 2 (UNDERSTAND → ask → user replies → UNDERSTAND → execute) | varies |

---

## Data Flow (contracts)

```
┌──────────────┐     ┌─────────────────────┐     ┌────────────────┐
│ LLM Provider │────▶│    Normalizer        │────▶│   Agent Loop   │
│ (Gemini/     │     │ (validates output,   │     │ (state machine,│
│  Bedrock)    │◀────│  maps tool names)    │     │  goal tracking)│
└──────────────┘     └─────────────────────┘     └───────┬────────┘
                                                          │
                     ┌─────────────────────┐              │
                     │   MCP Pipeline       │◀────────────┘
                     │ (middleware: audit,   │
                     │  rate limit, retry)   │
                     └──────────┬───────────┘
                                │
                     ┌──────────▼───────────┐
                     │  Discord Connectors   │
                     │  (**kwargs pattern)   │
                     └──────────────────────┘

```

---

## Prompt Structure (1 unified prompt)

```markdown
# System Prompt
You are AuraFactory...

## Output Format (MUST follow exactly)
Every response MUST be valid JSON in ONE of these formats:
{"action": "respond", "message": "..."} 
{"action": "execute", "plan_summary": "...", "tool_calls": [{name, arguments}...]}
{"action": "clarify", "question": "..."}

## When evaluating results (EVALUATE phase):
{"action": "done", "response": "..."}
{"action": "continue", "tool_calls": [...], "reason": "..."}  
{"action": "ask_user", "question": "..."}
{"action": "failed", "response": "..."}

## Rules
- IDs MUST be strings (not numbers) — Discord snowflakes lose precision as numbers
- If user says "ok"/"yes" — check the plan in history, DO NOT ask what they want
- If tool returns error "not found" — the ID is stale, re-fetch context and retry
- Execute dependencies in order: create parent before child
- After creating something, USE ITS RETURNED ID for subsequent steps
- Respond in the SAME language as the user

```

---

## Sự khác biệt vs v3.1/v4 (tại sao v5)

| Aspect | v3.1/v4 (hiện tại) | v5 (đề xuất) |
| --- | --- | --- |
| LLM calls per action | 3 (plan + reflect + assemble) | 2 (understand + evaluate) |
| Goal tracking | `message` raw (fails on "ok") | `effective_goal` persisted |
| Failure handling | Give up or infinite loop | LLM decides retry/skip/fail |
| Dependency resolution | Placeholder strings | Explicit `$stepN.field` forward |
| Output format | Function calling (tools) + free text | **Structured JSON always** — easier to parse |
| Prompt count | 4 separate prompts | 1 unified prompt |
| State machine | Implicit in code flow | Explicit enum (IDLE/UNDERSTAND/ACT/EVALUATE/PAUSE) |

---

## Implementation Plan

1. Rewrite `unified_agent.py` with explicit state machine
2. Merge UNIFIED_SYSTEM_PROMPT + REFLECT_PROMPT + ASSEMBLE_PROMPT into 1
3. Add `_resolve_dependencies()` for forward ID injection
4. Add `_resolve_effective_goal()` (already partially exists)
5. Keep: MCP pipeline, connectors, spec_loader, skills, middleware — unchanged

