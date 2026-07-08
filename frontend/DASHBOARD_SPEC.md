# AuraFactory Dashboard v2 — SPEC

---

## Layout Structure

```
┌──────────────────────────────────────────────────────────────┐
│ Navbar: Logo | Server Selector | User Avatar | Lang | Logout │
├───────────┬──────────────────────────────────────────────────┤
│ Sidebar   │  Main Chat Area                                  │
│ (280px)   │                                                  │
│           │  ┌────────────────────────────────────────────┐  │
│ ┌───────┐ │  │ Chat Messages (scrollable)                 │  │
│ │Session│ │  │                                            │  │
│ │History│ │  │ • User messages (right-aligned)            │  │
│ │       │ │  │ • Bot responses (left-aligned, markdown)   │  │
│ │▶Today │ │  │ • Approval cards (inline, interactive)     │  │
│ │ •ses1 │ │  │ • Clarify questions (inline)               │  │
│ │ •ses2 │ │  │                                            │  │
│ │       │ │  ├────────────────────────────────────────────┤  │
│ │▶Hôm qua│ │  │ Input bar + Send button                   │  │
│ │ •ses3 │ │  └────────────────────────────────────────────┘  │
│ └───────┘ │                                                  │
│           ├──────────────────────────────────────────────────┤
│ ┌───────┐ │  Right Panel (collapsible, 300px)                │
│ │Server │ │  ┌────────────────────────────────────────────┐  │
│ │Info   │ │  │ Tab: Structure | Audit Log                 │  │
│ │       │ │  │                                            │  │
│ │Ch: 12 │ │  │ [Structure tab]                            │  │
│ │Roles:5│ │  │   📁 THÔNG BÁO                            │  │
│ │Mem:34 │ │  │     # rules                               │  │
│ └───────┘ │  │     # announcements                       │  │
│           │  │   📁 CHAT                                  │  │
│ ┌───────┐ │  │     # general                             │  │
│ │Bot    │ │  │     🔊 voice-1                            │  │
│ │Admin  │ │  │                                            │  │
│ │(key)  │ │  │ [Audit tab]                               │  │
│ └───────┘ │  │   ✅ Created #test-ch — 2 min ago         │  │
│           │  │   ❌ Ban failed — 5 min ago                │  │
│           │  └────────────────────────────────────────────┘  │
└───────────┴──────────────────────────────────────────────────┘
```

---

## Components

### 1. Navbar (giữ nguyên + tối ưu)
- Logo + title "AuraFactory"
- Server selector dropdown (guild list)
- User avatar + name
- Language toggle (VI/EN)
- Logout button

### 2. Sidebar — Left (280px)

#### Session History (NEW — kiểu Gemini)
- List sessions grouped by date: "Hôm nay", "Hôm qua", "Tuần này", "Trước đó"
- Each item shows: first message excerpt (truncated 50 chars)
- Click → load session chat history into Main Area
- "New Chat" button at top → create new session
- Active session highlighted

#### Server Info (giữ)
- Channel count, Role count, Member count
- Compact display

#### Bot Admin (giữ — API key update)
- Gemini API key input + update button
- Only visible to bot admins (BOT_ADMIN_IDS)

### 3. Main Chat Area (center)

#### Messages Panel
- Scrollable message list
- User messages: right-aligned, bubble style
- Bot messages: left-aligned, markdown rendered
- **Approval cards inline** (not separate panel):
  ```html
  <div class="approval-card">
    <div class="plan-summary">Tạo 3 kênh và 2 role</div>
    <div class="plan-steps">
      <div class="step">1. discord.roles.create — "Teacher"</div>
      <div class="step">2. discord.channels.create — "#classroom"</div>
    </div>
    <div class="risk-badge risk-medium">MEDIUM</div>
    <div class="approval-actions">
      <button class="btn-approve">✅ Duyệt</button>
      <button class="btn-reject">❌ Từ chối</button>
    </div>
  </div>
  ```
- **Clarify questions inline** (NEW):
  ```html
  <div class="clarify-card">
    <p class="clarify-summary">Cần thêm thông tin:</p>
    <ul class="clarify-questions">
      <li>Bạn muốn tạo role gì?</li>
      <li>Cần bao nhiêu voice channel?</li>
    </ul>
  </div>
  ```

#### Input Bar
- Text input + Send button
- Shift+Enter = newline, Enter = send

### 4. Right Panel (collapsible, 300px)

#### Tab: Server Structure
- Tree view of current server:
  - Categories (📁) → Channels (# text, 🔊 voice, 📢 news, 💬 forum)
  - Roles list with colors
- Data from `server_snapshots` table (refreshes on guild select)

#### Tab: Audit Log
- Recent tool executions (last 20)
- Each entry: icon (✅/❌) + tool name + time ago + user
- Data from `audit_log` table

---

## BỎ (so với v1)

| Bỏ | Lý do |
|---|---|
| "Chế độ Assistant" toggle | UX confusing, không sync với Discord |
| "Hướng dẫn nhanh" section | Chuyển thành empty state khi chưa có session |
| Separate Approval panel (right side) | Gộp inline vào chat messages |

---

## API Endpoints Required

### Existing (keep):
- `POST /api/chat` — send message, get response
- `GET /api/guilds` — list user's guilds
- `GET /api/guilds/{id}/info` — server info (channels/roles count)
- `POST /api/approve/{plan_id}` — approve plan
- `POST /api/reject/{plan_id}` — reject plan
- `POST /api/admin/gemini-key` — update API key

### New:
```
GET /api/sessions?guild_id={id}
  → Returns list of sessions for this guild+user
  → Response: [{id, first_message, created_at, last_active_at}]

GET /api/sessions/{session_id}/history
  → Returns full chat history for a session
  → Response: {id, history: [{role, content, timestamp}], guild_id}

POST /api/sessions/new?guild_id={id}
  → Creates a new session, returns session_id
  → Response: {id, created_at}

GET /api/audit?guild_id={id}&limit=20
  → Returns recent audit log entries
  → Response: [{tool_name, success, user_id, executed_at, duration_ms}]

GET /api/server/{guild_id}/structure
  → Returns server structure tree (categories + channels + roles)
  → Response: {categories: [...], standalone_channels: [...], roles: [...]}
```

---

## Data Flow (sync with Discord)

```
Discord Bot                    Dashboard Web
    │                              │
    │ (user sends command)         │ (user types in chat)
    ▼                              ▼
┌──────────────────────────────────────────┐
│         sessions.history (JSONB)          │  ← SINGLE SOURCE OF TRUTH
│         requests table (status flow)      │
│         plans + plan_steps               │
│         audit_log                        │
└──────────────────────────────────────────┘
    │                              │
    ▼                              ▼
Discord messages              Dashboard UI renders
(bot reply in channel)        (chat bubbles + approvals)
```

**Key insight:** Khi user chat trên Discord, session.history được update.
Khi user chat trên Dashboard, cùng session.history được update.
→ Cả hai đều thấy cùng conversation.

---

## Session History Logic

```python
# List sessions (sidebar)
SELECT id, 
       history->0->>'content' as first_message,
       created_at, 
       last_active_at
FROM sessions
WHERE guild_id = $1 AND user_id = $2
ORDER BY last_active_at DESC
LIMIT 50;

# Load session history (click on session)
SELECT history FROM sessions WHERE id = $1;

# New session
INSERT INTO sessions (guild_id, user_id, user_role, history)
VALUES ($1, $2, 'admin', '[]')
RETURNING id, created_at;
```

---

## Tech Stack (no change)
- Backend: FastAPI (existing `api_routes.py`)
- Frontend: Vanilla JS + CSS (existing, no framework)
- Template: Jinja2 (`dashboard.html`)
- Markdown: marked.js (already included)
