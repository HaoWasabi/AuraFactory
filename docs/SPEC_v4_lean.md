# AuraFactory — SPEC v4 (Final Complete)

**Version:** 4.0 | **Date:** 2026-07-07 | **Track:** Built with AWS (AABW, Jul 8–12)

---

## 1. Bài toán & Giá trị

### 1.1. Vấn đề thực tế

Quản trị Discord server yêu cầu hàng chục thao tác thủ công lặp lại:

| Pain Point | Thao tác thủ công | Thời gian trung bình |
| --- | --- | --- |
| Setup server mới | Tạo 5–15 categories, 20–50 channels, 5–10 roles, set permissions cho từng cặp role/channel | 30–90 phút |
| Restructure server cũ | Xóa/tạo/di chuyển/đổi tên channels lẻ tẻ | 15–45 phút |
| Set permissions | Click vào từng channel → thêm role → bật/tắt từng quyền (x20 channels = 100+ thao tác) | 20–60 phút |
| Moderation lặp lại | Kick/ban/timeout + ghi lý do + thông báo | 2–5 phút/case |

**Hệ quả:** Admin mất thời gian vào thao tác cơ học thay vì quản lý cộng đồng. Server mới setup lộn xộn vì thiếu kinh nghiệm. Sai permission gây lỗ hổng bảo mật.

### 1.2. Giải pháp

**AuraFactory** — AI Agent tự động hoá setup & management Discord server qua ngôn ngữ tự nhiên (tiếng Việt + tiếng Anh).

### 1.3. Giá trị cốt lõi (1 câu)

> Admin mô tả server mình muốn bằng lời → Bot lên kế hoạch → Admin duyệt → Bot tự thực thi hết.

### 1.4. Không phải thin wrapper vì:

- Bot **thực sự thực thi hành động** (tạo channel, role, set permission trên Discord) — không chỉ chat.
- Có **pipeline xử lý** (classify → plan → approve → execute → report) — không phải 1 prompt tĩnh.
- Có **risk assessment + human-in-the-loop** — AI không tự ý thực hiện hành động nguy hiểm.
- Có **ReAct reasoning loop** — AI suy luận multi-step, xử lý lỗi giữa chừng.

---

## 2. Scope — Những gì AuraFactory làm

### 2.1. SETUP (Thiết lập server từ đầu)

Dựa trên quy trình setup chuẩn Discord server:

| Thao tác | Input mẫu (ngôn ngữ tự nhiên) | Tools sử dụng |
| --- | --- | --- |
| **Tạo Categories** | "Tạo danh mục THÔNG BÁO, HỌC TẬP, GIẢI TRÍ" | `create_category` |
| **Tạo Text Channels** | "Trong HỌC TẬP tạo #vocabulary, #grammar, #listening" | `create_text_channel` |
| **Tạo Voice Channels** | "Thêm voice channel Speaking Room trong Practice" | `create_voice_channel` |
| **Tạo Roles** | "Tạo role Teacher (xanh), Student (vàng), Moderator (đỏ)" | `create_role` |
| **Set Permissions** | "Teacher có quyền manage channels, Student chỉ xem và chat" | `set_channel_permissions` |
| **Setup hoàn chỉnh** | "Setup server học tiếng Anh với đầy đủ kênh và role" | Tất cả tools trên, multi-step |

**Use case đặc biệt — Setup từ template:**

```
User: "Setup server gaming với channels cho Valorant, LOL, Minecraft — mỗi game có voice + text, role riêng"
→ Bot sinh plan 15+ bước → Admin duyệt → Thực thi hết

```

### 2.2. MANAGEMENT (Quản trị đang hoạt động)

| Thao tác | Input mẫu | Tools sử dụng |
| --- | --- | --- |
| **Restructure** | "Chuyển #off-topic vào category GIẢI TRÍ" | `move_channel` |
| **Rename** | "Đổi tên channel #general thành #chào-mừng" | `rename_channel` |
| **Edit channel** | "Set slowmode 10s cho #general, thêm topic" | `edit_channel` |
| **Dọn dẹp** | "Xóa tất cả channel trong category CŨ" | `delete_channel` (bulk, HITL) |
| **Role management** | "Xóa role Newbie, đổi màu Admin thành đỏ" | `delete_role`, `edit_role` |
| **Permission audit** | "Liệt kê ai có quyền gì ở #admin-chat" | `get_channel_permissions` |
| **Sync permissions** | "Sync permissions channel này với category cha" | `sync_permissions` |

### 2.3. SERVER SETTINGS (Cấu hình server)

| Thao tác | Input mẫu | Tools sử dụng |
| --- | --- | --- |
| **Server Profile** | "Đổi tên server thành 'English Hub', thêm mô tả" | `edit_server_profile` |
| **Verification Level** | "Set verification level cao nhất — yêu cầu phone" | `set_verification_level` |
| **Invite Link** | "Tạo link mời vĩnh viễn cho channel #welcome" | `create_invite` |
| **Custom Emoji** | "Upload emoji :pepe: từ link này" | `upload_emoji` |
| **Delete Emoji** | "Xóa emoji :old_emoji:" | `delete_emoji` |
| **Webhook** | "Tạo webhook cho #notifications để nhận alert từ GitHub" | `create_webhook` |
| **System Channel** | "Set #welcome làm system channel (chào thành viên mới)" | `edit_server_profile` |

### 2.4. AUTOMATION & SAFETY (Tự động hóa & bảo mật)

| Thao tác | Input mẫu | Tools sử dụng |
| --- | --- | --- |
| **AutoMod — Block keywords** | "Chặn từ: 'scam', 'free nitro', link lạ" | `create_automod_rule` |
| **AutoMod — Anti-spam** | "Block tin nhắn lặp lại >5 lần/phút" | `create_automod_rule` |
| **AutoMod — Block links** | "Chặn tất cả link ngoại trừ youtube.com" | `create_automod_rule` |
| **Remove AutoMod Rule** | "Xóa rule chặn link" | `delete_automod_rule` |
| **Scheduled Event** | "Tạo event 'Speaking Night' thứ 7, 8pm, kênh voice" | `create_event` |

### 2.5. MODERATION (Kiểm duyệt)

| Thao tác | Input mẫu | Risk | Tools |
| --- | --- | --- | --- |
| **Timeout** | "Mute @spammer 24h lý do spam" | HIGH (HITL) | `timeout_member` |
| **Remove Timeout** | "Gỡ mute cho @user" | MEDIUM | `remove_timeout` |
| **Kick** | "Kick @troll lý do vi phạm luật" | HIGH (HITL) | `kick_member` |
| **Ban** | "Ban @hacker xóa tin 7 ngày" | CRITICAL (HITL) | `ban_member` |
| **Unban** | "Gỡ ban cho user#1234" | HIGH (HITL) | `unban_member` |
| **List Bans** | "Cho xem danh sách bị ban" | LOW | `list_bans` |

### 2.6. QUERY (Hỏi đáp — read-only, không cần duyệt)

| Thao tác | Input mẫu | Tools |
| --- | --- | --- |
| **Liệt kê channels** | "Server có bao nhiêu channel?" | `list_channels` |
| **Liệt kê roles** | "Cho xem danh sách roles" | `list_roles` |
| **Kiểm tra permissions** | "Role Moderator có quyền gì?" | `get_role_permissions` |
| **Tổng quan structure** | "Cho tôi xem cấu trúc server hiện tại" | `list_categories` + `list_channels` |
| **Server info** | "Server có bao nhiêu member? Boost level?" | `get_server_info` |
| **Active invites** | "Liệt kê tất cả invite link đang active" | `list_invites` |
| **AutoMod rules** | "Server đang có rule automod nào?" | `list_automod_rules` |

---

## 3. Demo Scenarios (Chạy thật)

### Scenario 1: Setup hoàn chỉnh (ADMIN_COMPLEX → AdminAgent)

```
Admin: "Setup server học tiếng Anh:
  - Category Lessons: #vocabulary, #grammar, #listening
  - Category Practice: #daily-challenge, voice Speaking Room  
  - Category Cộng đồng: #giới-thiệu, #off-topic
  - Role: Teacher (xanh, manage channels), Student (vàng, chỉ chat)"

Bot (2–3s): 
📋 Kế hoạch thực thi (11 bước):
1. Tạo category "Lessons"
2. Tạo #vocabulary trong Lessons
3. Tạo #grammar trong Lessons
4. Tạo #listening trong Lessons
5. Tạo category "Practice"
6. Tạo #daily-challenge trong Practice
7. Tạo 🔊 Speaking Room trong Practice
8. Tạo category "Cộng đồng"
9. Tạo #giới-thiệu trong Cộng đồng
10. Tạo #off-topic trong Cộng đồng
11. Tạo role Teacher (màu xanh, manage_channels=true)
12. Tạo role Student (màu vàng)
13. Set permissions: Teacher manage all, Student view+send only

⚠️ Risk: HIGH (bulk create 7 channels + 3 categories + 2 roles + permissions)
👉 Gõ "duyệt" để thực thi, "sửa" để chỉnh, "hủy" để bỏ.

Admin: "duyệt"

Bot: Đang thực thi...
✅ 1/13: Tạo category "Lessons"
✅ 2/13: Tạo #vocabulary
✅ 3/13: Tạo #grammar
...
✅ 13/13: Set permissions cho Student
🎉 Hoàn tất! Server học tiếng Anh đã sẵn sàng.

```

### Scenario 2: Lệnh đơn giản (FAST_TRACK → FastTrackAgent)

```
Admin: "tạo channel #announcements"

Bot (1–2s): ✅ Đã tạo text channel #announcements

```

### Scenario 3: Hỏi đáp (ASSISTANT → AssistantAgent)

```
User: "Server có bao nhiêu roles?"

Bot (1s): Server hiện có 5 roles: @everyone, Admin, Moderator, Member, Bot.

```

### Scenario 4: Restructure (ADMIN_COMPLEX)

```
Admin: "Dọn lại server — chuyển #memes và #random vào category GIẢI TRÍ, xóa category CŨ"

Bot:
📋 Kế hoạch (3 bước):
1. Chuyển #memes → GIẢI TRÍ
2. Chuyển #random → GIẢI TRÍ
3. Xóa category "CŨ" (trống)

⚠️ Risk: HIGH (xóa category)
👉 Gõ "duyệt" để thực thi.

```

### Scenario 5: Moderation (FAST_TRACK, HITL)

```
Admin: "timeout @spammer 1 giờ lý do spam liên tục"

Bot:
⚠️ Hành động cần duyệt:
• Timeout @spammer trong 1 giờ
• Lý do: spam liên tục
👉 Gõ "duyệt" để thực hiện.

Admin: "duyệt"

Bot: ✅ Đã timeout @spammer 1 giờ. Lý do: spam liên tục.

```

---

## 4. Architecture

```
┌─────────────────────────────────────────────────────┐
│  Layer 1: INPUT                                     │
│  └── Discord Bot (nextcord) — listen & respond      │
├─────────────────────────────────────────────────────┤
│  Layer 2: GATEWAY (Control Plane)                   │
│  ├── Rate Limiter (token-bucket, 20 req/min/user)   │
│  ├── Role Detector (owner/admin/mod/member)         │
│  ├── Permission Gate (chặn member gọi admin tools)  │
│  └── Session Manager (context per user per guild)   │
├─────────────────────────────────────────────────────┤
│  Layer 3: AGENTS (Brain)                            │
│  ├── Classifier (intent routing)                    │
│  ├── FastTrackAgent (1 action, no plan needed)      │
│  ├── AdminAgent (ReAct + Plan + HITL)               │
│  └── AssistantAgent (Q&A, no tools)                 │
├─────────────────────────────────────────────────────┤
│  Layer 4: TOOLS (MCP Protocol)                      │
│  └── Discord MCP Server (20+ tools → Discord API)  │
├─────────────────────────────────────────────────────┤
│  Layer 5: LLM PROVIDER (Swappable)                  │
│  ├── Phase 1: Gemini 2.5 Flash                      │
│  └── Phase 2: Amazon Bedrock (Claude/Nova)          │
└─────────────────────────────────────────────────────┘

```

---

## 5. Agent Layer — Chi tiết

### 5.1. Intent Classifier

**Input:** User message (raw text) + user_role**Output:** `FAST_TRACK` | `ADMIN_COMPLEX` | `ASSISTANT`**Method:** LLM call (20 tokens output) + heuristic fallback

```
Classification Rules:
─────────────────────
ASSISTANT:
  - Câu hỏi (có "?", "bao nhiêu", "là gì", "how", "what")
  - Greeting ("hi", "hello", "xin chào")
  - Help request ("giúp", "help", "hướng dẫn")

FAST_TRACK:
  - 1 hành động rõ ràng: "tạo channel X", "xóa role Y", "kick @user"
  - 1 verb + 1 object, không mơ hồ

ADMIN_COMPLEX:
  - Multiple actions: "tạo 3 channel và 2 role"
  - Vague/planning: "setup server gaming", "dọn lại server"
  - Bulk operations: "xóa tất cả channel cũ"
  - Keywords: "setup", "thiết lập", "cấu hình", "toàn bộ", "redesign"

```

**Fallback Strategy:**

1. Gọi LLM → parse output
2. Nếu LLM fail (safety block, timeout) → dùng heuristic (keyword matching)
3. Nếu cả 2 unclear → default ASSISTANT (an toàn nhất)

### 5.2. FastTrack Agent

**Khi nào:** 1 hành động đơn, rõ ràng, không cần lên plan.

**Flow:**

```
User message
    │
    ▼
LLM Extract (1 call, ~300 tokens)
→ Output: {tool: "create_text_channel", params: {name: "general", category: "CHAT"}}
    │
    ▼
Risk Check:
├── LOW/MEDIUM → Execute ngay → Report result
└── HIGH/CRITICAL → Show confirmation → Wait approve → Execute
    │
    ▼
Response: "✅ Đã tạo #general trong category CHAT"

```

**Token budget:** ~600 tokens total (1 LLM call to extract + format response)

**System Prompt (FastTrack):**

```
You are AuraFactory FastTrack executor. Extract ONE tool call from user request.

Output EXACTLY this JSON (no other text):
{"tool": "<tool_name>", "params": {<parameters>}, "response": "<confirmation message in user's language>"}

Available Tools:
{tools_block}

Server Context:
{server_context}

Respond in the same language the user used.

```

### 5.3. Admin Agent (ReAct + HITL)

**Khi nào:** Multi-step operations, bulk, vague requests cần planning.

**ReAct Loop (max 5 iterations):**

```
┌─── Iteration 0 ───────────────────────────────────┐
│ Input: user prompt + system prompt (tools + context)│
│ LLM Output:                                        │
│   Thought: "User wants a full English learning     │
│             server. I need to create categories,   │
│             channels, and roles. This is HIGH risk │
│             bulk operation — I should output a     │
│             plan for approval."                    │
│   Action: FINISH                                   │
│   Action Input: {"message": "📋 Kế hoạch...",     │
│                  "approval_required": true}         │
└────────────────────────────────────────────────────┘
         │
         ▼ (User approves)
┌─── Execution Phase ────────────────────────────────┐
│ For each step in plan:                             │
│   1. Call MCP tool                                 │
│   2. Check result (success/fail)                   │
│   3. Report progress to user                       │
│   4. If fail → stop, report, ask user              │
└────────────────────────────────────────────────────┘

```

**System Prompt (AdminAgent):**

```
You are AuraFactory AdminAgent — executing Discord server management via ReAct.

RESPONSE FORMAT (strict):
Thought: <reasoning in English>
Action: <tool_name OR FINISH OR CLARIFY>
Action Input: <JSON params>

TERMINAL ACTIONS:
- FINISH → {"message": "response in user's language"}
- FINISH with plan → {"message": "<numbered plan>", "approval_required": true}
- CLARIFY → {"message": "question in user's language"}

RULES:
- ONE action per turn.
- For HIGH/CRITICAL risk or bulk operations (≥3 steps): 
  Output full numbered plan, then FINISH with approval_required=true.
- For LOW/MEDIUM single action: execute directly.
- If tool fails: try alternative or FINISH with error explanation.
- Max {max_iter} iterations.
- Progress: report every step during execution.

RISK LEVELS:
- LOW: read-only (list_channels, list_roles)
- MEDIUM: create 1 item (create_channel, create_role)
- HIGH: bulk create (≥3), delete, permission changes
- CRITICAL: bulk delete, kick, ban

Available Tools:
{tools_block}

Server Context:
{server_context}

Language: Thought → English. Messages → same as user's language.

```

### 5.4. Assistant Agent

**Khi nào:** Câu hỏi, help, greeting — không gọi tool ghi.

**Flow:**

```
User question → LLM answer (dùng server context nếu có) → Response

```

**Allowed tools (read-only):** `list_channels`, `list_roles`, `list_categories`, `get_role_permissions`

**System Prompt (Assistant):**

```
You are AuraFactory Assistant — answering questions about Discord server.
Use the server context below to answer accurately.
Do NOT perform any write actions (create, delete, modify).
If user asks to DO something (not just ask), respond:
"Bạn muốn tôi thực hiện thao tác này? Hãy nói rõ hơn để tôi lên kế hoạch."

Server Context:
{server_context}

Respond in the same language the user used.

```

---

## 6. Human-in-the-Loop (HITL)

### 6.1. Khi nào cần HITL:

| Condition | Risk Level | Ví dụ |
| --- | --- | --- |
| Bulk create ≥3 items | HIGH | "tạo 5 channel + 2 role" |
| Bất kỳ delete nào | HIGH | "xóa channel #old" |
| Permission changes | HIGH | "set Teacher manage channels" |
| Moderation actions | HIGH/CRITICAL | "kick @user", "ban @user" |
| Bulk delete | CRITICAL | "xóa tất cả channel trong category X" |

### 6.2. Approval Flow:

```
Bot sinh plan/action
    │
    ▼
Format & hiển thị cho user:
┌─────────────────────────────────────────┐
│ 📋 Kế hoạch thực thi (N bước):         │
│ 1. [action 1]                           │
│ 2. [action 2]                           │
│ ...                                     │
│                                         │
│ ⚠️ Risk: HIGH/CRITICAL — [lý do]       │
│ 👉 "duyệt" / "sửa" / "hủy"            │
└─────────────────────────────────────────┘
    │
    ▼
Wait for user response:
├── "duyệt" / "approve" / "ok" / "đi" → Execute
├── "sửa <nội dung>" → Re-plan with modification
└── "hủy" / "cancel" / "thôi" → Discard, acknowledge

```

### 6.3. Approval Storage:

```python
# In-memory (đủ cho demo, plan ko persistent qua restart)
pending_approvals = {
    approval_id: {
        "trace_id": str,
        "guild_id": int,
        "user_id": int,
        "plan_steps": [...],
        "created_at": timestamp,
        "ttl": 30 minutes,  # Auto-expire
    }
}

```

### 6.4. Execution sau Approval:

```
For each step in approved_plan:
    │
    ├── Call MCP tool
    │   ├── Success → log + report progress
    │   └── Fail → stop, report error, ask user:
    │       "❌ Bước 4/7 lỗi: [error]. Gõ 'tiếp tục' để bỏ qua, 'hủy' để dừng."
    │
    ├── Report: "✅ 4/7: Tạo #grammar"
    │
    └── Next step...

Final: "🎉 Hoàn tất N/N bước!"

```

---

## 7. MCP Tool Layer

### 7.1. Discord MCP Server — Full Tool List (30 tools)

🏗️ Setup Tools (Tạo mới):

| # | Tool | Params | Risk | Mô tả |
| --- | --- | --- | --- | --- |
| 1 | `create_category` | `{name, position?}` | MEDIUM | Tạo category (nhóm channels) |
| 2 | `create_text_channel` | `{name, category_id?, topic?, slowmode?}` | MEDIUM | Tạo text channel |
| 3 | `create_voice_channel` | `{name, category_id?, user_limit?}` | MEDIUM | Tạo voice channel |
| 4 | `create_role` | `{name, color?, permissions?, hoist?, mentionable?}` | MEDIUM | Tạo role mới |
| 5 | `create_invite` | `{channel_id, max_age?, max_uses?, temporary?}` | MEDIUM | Tạo invite link |
| 6 | `create_webhook` | `{channel_id, name, avatar_url?}` | MEDIUM | Tạo webhook cho channel |
| 7 | `create_event` | `{name, start_time, end_time?, channel_id?, description?, type?}` | MEDIUM | Tạo scheduled event |
| 8 | `upload_emoji` | `{name, image_url}` | MEDIUM | Upload custom emoji |

🔧 Management Tools (Sửa đổi):

| # | Tool | Params | Risk | Mô tả |
| --- | --- | --- | --- | --- |
| 9 | `rename_channel` | `{channel_id, new_name}` | MEDIUM | Đổi tên channel |
| 10 | `move_channel` | `{channel_id, category_id, position?}` | MEDIUM | Di chuyển channel sang category khác |
| 11 | `edit_channel` | `{channel_id, topic?, slowmode?, nsfw?}` | MEDIUM | Sửa settings channel |
| 12 | `edit_role` | `{role_id, name?, color?, permissions?, hoist?}` | MEDIUM | Sửa role (tên, màu, quyền) |
| 13 | `edit_server_profile` | `{name?, icon_url?, description?, system_channel_id?}` | HIGH | Sửa profile server |
| 14 | `set_verification_level` | `{level: none/low/medium/high/highest}` | HIGH | Set mức xác minh thành viên |

🔐 Permission Tools:

| # | Tool | Params | Risk | Mô tả |
| --- | --- | --- | --- | --- |
| 15 | `set_channel_permissions` | `{channel_id, role_id, allow[], deny[]}` | HIGH | Set permission override cho role/channel |
| 16 | `sync_permissions` | `{channel_id}` | HIGH | Sync permissions với category cha |
| 17 | `set_role_permissions` | `{role_id, permissions{}}` | HIGH | Set server-wide permissions cho role |

🤖 Automation Tools:

| # | Tool | Params | Risk | Mô tả |
| --- | --- | --- | --- | --- |
| 18 | `create_automod_rule` | `{name, trigger_type, trigger_metadata, actions[]}` | HIGH | Tạo AutoMod rule (keyword filter, spam, link block) |
| 19 | `delete_automod_rule` | `{rule_id}` | HIGH | Xóa AutoMod rule |

🛡️ Moderation Tools:

| # | Tool | Params | Risk | Mô tả |
| --- | --- | --- | --- | --- |
| 20 | `timeout_member` | `{user_id, duration_seconds, reason?}` | HIGH | Timeout (1 phút → 28 ngày) |
| 21 | `remove_timeout` | `{user_id}` | MEDIUM | Gỡ timeout |
| 22 | `kick_member` | `{user_id, reason?}` | HIGH | Kick member |
| 23 | `ban_member` | `{user_id, reason?, delete_message_days?}` | CRITICAL | Ban vĩnh viễn |
| 24 | `unban_member` | `{user_id}` | HIGH | Gỡ ban |

🗑️ Delete Tools:

| # | Tool | Params | Risk | Mô tả |
| --- | --- | --- | --- | --- |
| 25 | `delete_channel` | `{channel_id}` | HIGH | Xóa channel |
| 26 | `delete_category` | `{category_id}` | HIGH | Xóa category (phải trống hoặc force) |
| 27 | `delete_role` | `{role_id}` | HIGH | Xóa role |
| 28 | `delete_emoji` | `{emoji_id}` | MEDIUM | Xóa custom emoji |

📊 Query Tools (Read-only):

| # | Tool | Params | Risk | Mô tả |
| --- | --- | --- | --- | --- |
| 29 | `list_channels` | `{category_id?}` | LOW | List channels (tùy chọn filter category) |
| 30 | `list_categories` | `{}` | LOW | List tất cả categories |
| 31 | `list_roles` | `{}` | LOW | List roles + permissions tóm tắt |
| 32 | `get_channel_permissions` | `{channel_id}` | LOW | Xem permission overrides chi tiết |
| 33 | `get_role_permissions` | `{role_id}` | LOW | Xem full permissions của role |
| 34 | `get_server_info` | `{}` | LOW | Tên, icon, member count, boost level, features |
| 35 | `list_invites` | `{}` | LOW | List invite links đang active |
| 36 | `list_bans` | `{}` | LOW | List users đang bị ban |
| 37 | `list_automod_rules` | `{}` | LOW | List AutoMod rules hiện tại |

### 7.2. Coverage Summary

| Server Settings Category | Tools covered | Coverage |
| --- | --- | --- |
| **Overview** (name, icon, description) | `edit_server_profile`, `get_server_info` | ✅ Full |
| **Roles** (create, edit, delete, permissions) | `create_role`, `edit_role`, `delete_role`, `set_role_permissions` | ✅ Full |
| **Emoji** (upload, delete) | `upload_emoji`, `delete_emoji` | ✅ Full |
| **Safety Setup** (verification level) | `set_verification_level` | ✅ Full |
| **AutoMod** (rules CRUD) | `create_automod_rule`, `delete_automod_rule`, `list_automod_rules` | ✅ Full |
| **Members/Moderation** (timeout, kick, ban, unban) | `timeout_member`, `remove_timeout`, `kick_member`, `ban_member`, `unban_member` | ✅ Full |
| **Channels** (CRUD + permissions + move) | 10 tools | ✅ Full |
| **Invites** (create, list) | `create_invite`, `list_invites` | ✅ Full |
| **Webhooks** (create) | `create_webhook` | ✅ Partial |
| **Events** (create) | `create_event` | ✅ Partial |
| **Integrations** (Twitch/YouTube) | — | ❌ Not supported (3rd party) |
| **Boost/Nitro** | — | ❌ Read-only by Discord |
| **Stickers/Soundboard** | — | ❌ API hạn chế |
| **Community Enable** | — | 🟡 Phase 2 (cần preconditions) |

**Tổng: 37 tools → bao phủ ~70% Discord Server Settings khả thi qua API.**

### 7.3. MCP Protocol

Tất cả tool calls đều đi qua MCP (Model Context Protocol):

```python
# Tool call format (JSON-RPC style)
{
    "method": "tools/call",
    "params": {
        "name": "create_text_channel",
        "arguments": {
            "guild_id": 123456,
            "name": "vocabulary",
            "category_id": 789012
        }
    }
}

# Response format
{
    "result": {
        "success": true,
        "data": {"channel_id": 111222, "name": "vocabulary"},
        "message": "Channel created successfully"
    }
}

# Error format
{
    "error": {
        "code": "DISCORD_API_ERROR",
        "message": "Missing Permissions",
        "details": {"required": "MANAGE_CHANNELS"}
    }
}

```

### 7.4. Tool Mode Filtering (Token Optimization)

AdminAgent không cần thấy tất cả 37 tools. Filter theo intent:

| Mode | Tools visible | ~Tokens | Khi nào |
| --- | --- | --- | --- |
| `setup` | create_* (8 tools) | ~200 | "setup server", "tạo..." |
| `manage` | edit_*, rename_*, move_*, delete_* (10 tools) | ~250 | "sửa", "đổi", "xóa", "chuyển" |
| `permissions` | set_*_permissions, sync_permissions (3 tools) | ~100 | "quyền", "permission" |
| `moderate` | timeout, kick, ban, unban (5 tools) | ~120 | "mute", "kick", "ban" |
| `automod` | create/delete_automod_rule (2 tools) | ~80 | "automod", "chặn", "filter" |
| `server` | edit_server_profile, set_verification_level, create_invite (3 tools) | ~100 | "server settings", "verification" |
| `query` | list_*, get_* (9 tools) | ~200 | Câu hỏi, "liệt kê", "cho xem" |
| `full` | All 37 tools | ~800 | Fallback (complex multi-domain) |

Classifier output kèm `mode` hint → Agent chỉ thấy tools liên quan → tiết kiệm ~60% tokens.

## 8. Gateway Layer

### 8.1. Rate Limiter

```
Token-bucket algorithm:
- Capacity: 20 requests
- Refill: 1 request per 3 seconds
- Per: user_id + guild_id
- Exceeded → "⏳ Bạn đang gửi quá nhanh, chờ vài giây."

```

### 8.2. Role Detector

```python
# Detect user's highest role in guild
def detect_role(member) -> str:
    if member == guild.owner:
        return "owner"
    if member.guild_permissions.administrator:
        return "admin"
    if member.guild_permissions.manage_channels or member.guild_permissions.manage_roles:
        return "moderator"
    return "member"

```

### 8.3. Permission Gate

```
Chỉ owner/admin mới gọi được:
- ADMIN_COMPLEX (setup, restructure, bulk ops)
- FAST_TRACK với tools ghi (create, delete, modify)

Moderator được gọi:
- FAST_TRACK moderation (timeout, kick)
- Nhưng KHÔNG được delete channel/role

Member chỉ:
- ASSISTANT (hỏi đáp)

```

### 8.4. Session Manager

```python
# Session = conversation context per user per guild
session = {
    "user_id": int,
    "guild_id": int,
    "history": [...],        # Last 5 messages (rolling window)
    "pending_approval": {},  # Current plan awaiting approval
    "created_at": timestamp,
    "expires_at": timestamp, # Auto-cleanup after 30 min idle
}

```

---

## 9. Server Context (Thay thế Knowledge Store)

Thay vì vector store phức tạp, dùng **live query + cache đơn giản**:

```python
async def get_server_context(guild_id: int) -> str:
    """
    Build server context string for LLM prompt.
    Gọi Discord API trực tiếp (cached 60s).
    """
    categories = await list_categories(guild_id)
    channels = await list_channels(guild_id)
    roles = await list_roles(guild_id)
    
    context = f"""Server hiện tại:
- Categories ({len(categories)}): {', '.join(c.name for c in categories)}
- Text channels ({len(text_chs)}): {', '.join('#'+c.name for c in text_chs[:15])}
- Voice channels ({len(voice_chs)}): {', '.join(c.name for c in voice_chs[:10])}
- Roles ({len(roles)}): {', '.join(r.name for r in roles[:10])}
"""
    return context  # ~200 tokens, đủ cho LLM biết server có gì

```

**Cache:** 60 giây TTL, invalidate khi bot thực hiện tool ghi.**Token budget:** ~200 tokens (thay vì 2000 tokens nếu full dump).

---

## 10. LLM Provider (Swappable)

### 10.1. Interface

```python
class BaseLLM(ABC):
    @abstractmethod
    async def generate(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str = "",
        temperature: float = 0.3,
        max_tokens: int = 1500,
        tools: Optional[List[Dict]] = None,
    ) -> LLMResponse:
        ...

@dataclass
class LLMResponse:
    content: str
    tool_calls: List[ToolCall]
    usage: UsageStats

```

### 10.2. Phase 1 — Gemini 2.5 Flash (Current)

```python
class GeminiLLM(BaseLLM):
    # Đang dùng, test mọi flow trước
    model = "gemini-2.5-flash"
    # Safety settings: BLOCK_NONE (đã config)

```

### 10.3. Phase 2 — Amazon Bedrock (Swap)

```python
class BedrockLLM(BaseLLM):
    """Drop-in replacement. Đổi 1 dòng config."""
    
    def __init__(self, model_id="anthropic.claude-3-5-sonnet-20241022-v2:0"):
        self._client = boto3.client("bedrock-runtime", region_name="us-east-1")
        self.model_id = model_id
    
    async def generate(self, messages, system_prompt, temperature, max_tokens, **kwargs):
        response = self._client.converse(
            modelId=self.model_id,
            messages=self._format_messages(messages),
            system=[{"text": system_prompt}],
            inferenceConfig={"temperature": temperature, "maxTokens": max_tokens},
        )
        return self._parse_response(response)

```

**Switch:**

```python
# config.py
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")  # "gemini" | "bedrock"

```

### 10.4. AWS Integration Points (Phase 2)

| Component | AWS Service | Vai trò trong pipeline |
| --- | --- | --- |
| LLM (reasoning) | **Bedrock Claude/Nova** | Classify intent, generate plan, ReAct reasoning |
| Guardrails | **Bedrock Guardrails** | Block prompt injection, filter toxic input |
| Server Knowledge | **Bedrock Knowledge Bases** | RAG: "server X có gì" + best practices |

---

## 11. Token Budget & Cost

### Per-request token estimate (Gemini 2.5 Flash):

| Flow | Input tokens | Output tokens | LLM calls | Total |
| --- | --- | --- | --- | --- |
| ASSISTANT | ~400 | ~200 | 1 (classify) + 1 (answer) | ~600 |
| FAST_TRACK | ~500 | ~100 | 1 (classify) + 1 (extract) | ~600 |
| ADMIN_COMPLEX (plan) | ~800 | ~400 | 1 (classify) + 1 (plan) | ~1200 |
| ADMIN_COMPLEX (execute 7 steps) | ~200/step | ~100/step | 7 tool calls | ~2100 |

**Gemini free tier:** ~15–20 req/min → đủ cho demo.

---

## 12. Error Handling

### 12.1. LLM Failures

| Error | Handling |
| --- | --- |
| Timeout | Retry 1 lần (2s backoff) → "Hệ thống chậm, thử lại." |
| Safety block (finish_reason=2) | Heuristic fallback (classifier) / Rephrase (admin) |
| Empty response | Return error message, don't crash |
| Rate limit (429) | Queue + "Đang xử lý, chờ..." |

### 12.2. Tool Failures

| Error | Handling |
| --- | --- |
| Discord API error | Report cụ thể: "❌ Lỗi tạo channel: tên trùng" |
| Permission denied (bot) | "Bot thiếu quyền. Kiểm tra role của bot." |
| Entity not found | "Channel/role không tồn tại." |
| Mid-execution failure | Stop, report progress (✅ 3/7 xong, ❌ bước 4 lỗi), ask user |

### 12.3. User Input Edge Cases

| Case | Handling |
| --- | --- |
| Quá vague ("setup đi") | CLARIFY: "Bạn muốn setup server cho mục đích gì?" |
| Quá dài (>1000 chars) | Truncate to 500, warn: "Message dài quá, tôi xử lý phần chính." |
| Nhập ngoài scope ("play nhạc") | ASSISTANT: "Tôi chỉ hỗ trợ quản trị server (tạo channel, role, permissions)." |
| Spam approve | Rate limit gate chặn |

---

## 13. File Structure

```
AuraFactory/
├── app/
│   ├── main.py                       # FastAPI + Discord bot startup + DI wiring
│   ├── gateway/
│   │   ├── rate_limiter.py           # Token-bucket
│   │   ├── role_detector.py          # Discord role → permission level  
│   │   ├── permission_gate.py        # Chặn unauthorized commands
│   │   └── session_manager.py        # Session per user per guild
│   ├── agents/
│   │   ├── base.py                   # BaseAgent ABC (LLM call + retry + cost)
│   │   ├── contracts.py              # TaskAssignment, TaskResult, IntentType
│   │   ├── orchestrator.py           # Entry point: classify → route → return
│   │   ├── classifier.py             # LLM + heuristic fallback
│   │   ├── admin_agent.py            # ReAct loop + plan + HITL + execute
│   │   ├── fast_track.py             # 1 LLM → 1 tool → done
│   │   └── assistant_agent.py        # Q&A, read-only
│   ├── mcp/
│   │   ├── client.py                 # MCPClient — dispatch calls to servers
│   │   ├── protocol.py               # JSON-RPC types, ToolResult
│   │   └── servers/
│   │       └── discord_server.py     # All Discord tools implementation
│   └── infra/
│       ├── llm/
│       │   ├── base.py               # BaseLLM interface + LLMResponse
│       │   ├── gemini.py             # Phase 1
│       │   └── bedrock.py            # Phase 2
│       └── cache.py                  # Simple TTL cache for server context
├── prompts/
│   ├── classifier.md                 # Classification prompt
│   ├── admin.md                      # AdminAgent system prompt  
│   ├── fast_track.md                 # FastTrack extraction prompt
│   └── assistant.md                  # Assistant prompt
├── skills/                           # MCP tool definitions (.md)
│   ├── channels.md
│   ├── roles.md
│   ├── permissions.md
│   └── moderation.md
├── requirements.txt
├── Dockerfile
├── render.yaml
└── docs/
    └── SPEC_v4_lean.md               # This file

```

---

## 14. Trạng thái hiện tại & Roadmap Fix

### ✅ Đang hoạt động:

- Discord bot connect & nhận message
- Gateway (rate limit, session, role detection)
- Classifier (LLM + heuristic fallback)
- MCP Discord Server (tools registered, 4 connectors chạy ổn)
- AdminAgent ReAct loop (code structure hoàn chỉnh)
- Approval API endpoint

### 🔴 Blocking bugs (Fix trước khi demo):

| # | Bug | Root cause | Fix |
| --- | --- | --- | --- |
| 1 | AdminAgent FINISH ngay (tools = "No tools available") | `mcp_client` không inject đúng vào AdminAgent | Check DI wiring trong main.py |
| 2 | System prompt mất sau iteration 0 | `system_prompt=None` từ iter 1 | Luôn pass system_prompt hoặc prepend vào messages |
| 3 | Approval flow không resume | Chưa wire "duyệt" → execute approved plan | Thêm approval detection trong session |

### 🟡 Cần hoàn thiện (sau khi bugs fixed):

| # | Feature | Effort | Impact |
| --- | --- | --- | --- |
| 4 | Progress reporting (gửi message mid-execution) | 2h | UX tốt hơn nhiều |
| 5 | Server context (live query thay vì None) | 2h | LLM biết server có gì |
| 6 | Error recovery (resume sau lỗi giữa chừng) | 3h | Robust hơn |
| 7 | FastTrack HITL cho moderation | 1h | An toàn hơn |

### 🟢 Tier 1 — Tools mới cơ bản (~3h total):

| # | Tool | Effort | Priority |
| --- | --- | --- | --- |
| 8 | `edit_server_profile` (name, icon, description) | 1h | P1 — setup cơ bản |
| 9 | `create_invite` (link mời) | 30m | P1 — onboarding flow |
| 10 | `set_verification_level` | 30m | P1 — bảo mật |
| 11 | `unban_member` + `list_bans` | 30m | P1 — moderation |
| 12 | `remove_timeout` + `list_invites` | 30m | P1 — bổ sung |

### 🟠 Tier 2 — Tools nâng cao (~5h total):

| # | Tool | Effort | Priority |
| --- | --- | --- | --- |
| 13 | `create_automod_rule` + `delete_automod_rule` + `list_automod_rules` | 3h | P2 — automation |
| 14 | `upload_emoji` + `delete_emoji` | 1h | P2 — customization |
| 15 | `create_event` | 1h | P2 — community |
| 16 | `create_webhook` | 30m | P2 — integration |

### 🔵 Phase 2 — AWS Swap:

| # | Task | Effort |
| --- | --- | --- |
| 8 | Viết `BedrockLLM(BaseLLM)` + Converse API | 3h |
| 9 | Config switch (env var) | 30m |
| 10 | Bedrock Guardrails thay heuristic | 2h |
| 11 | Test toàn bộ flow với Bedrock | 2h |

---

## 15. Tiêu chí "Done" cho Demo

### Must-have (blocking):

- [ ] Admin gõ setup command → nhận plan trong <5s
- [ ] Plan hiển thị rõ ràng (numbered + risk badge)
- [ ] Admin gõ "duyệt" → bot thực thi step-by-step
- [ ] Progress reporting mỗi bước (✅ 3/7...)
- [ ] Channels, roles, permissions tạo thật trên Discord
- [ ] Lệnh đơn giản (FAST_TRACK) hoạt động <3s
- [ ] HITL chặn đúng (HIGH/CRITICAL không tự ý thực thi)
- [ ] Permission gate (member không setup được)

### Should-have (nice for demo):

- [ ] Error recovery giữa chừng
- [ ] "sửa" plan trước khi duyệt
- [ ] Moderation commands (kick/timeout/ban/unban)
- [ ] Server context (bot biết server có gì)
- [ ] Server Settings (edit profile, verification level)
- [ ] AutoMod rule creation (keyword filter, anti-spam)
- [ ] Create invite link + list invites
- [ ] Upload/delete custom emoji
- [ ] Create scheduled events
- [ ] Create webhook

### Phase 2 (AWS):

- [ ] Bedrock Claude/Nova là LLM chính
- [ ] Bedrock Guardrails active
- [ ] Demo switch Gemini ↔ Bedrock live

