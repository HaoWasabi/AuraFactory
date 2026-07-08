# AuraFactory UI SPEC v3 — Language, Streaming, Polish

---

## 1. Language System (i18n)

### Rules:
- **Default language: English (en)** — ALL UI text renders in English on first load
- User can toggle language (en/vi) via button in navbar
- Language preference saved to `localStorage.lang`
- When language changes: ALL visible UI text updates instantly (no page reload)
- **Exceptions**: Chat message content already sent is NOT re-translated
- **Scope**: login.html, callback.html, dashboard.html — all pages use same i18n system

### Implementation:
```javascript
// i18n dictionary
const I18N = {
  en: {
    new_chat: "New Chat",
    sessions: "Sessions",
    today: "Today",
    yesterday: "Yesterday",
    this_week: "This Week",
    earlier: "Earlier",
    server_info: "Server Info",
    channels: "Channels",
    roles: "Roles",
    members: "Members",
    structure: "Structure",
    audit_log: "Audit Log",
    send: "Send",
    approve: "Approve",
    reject: "Reject",
    login_title: "Sign in with Discord",
    login_desc: "Manage your Discord server with AI",
    logout: "Log out",
    select_server: "Select server...",
    admin_panel: "Admin Panel",
    update_key: "Update API Key",
    no_sessions: "No conversations yet",
    type_message: "Type a message...",
    pending_approval: "Pending Approval",
    plan_steps: "steps",
    risk_level: "Risk",
    clarify_title: "Need more information",
    loading: "Loading...",
    lang_toggle: "VI",
  },
  vi: {
    new_chat: "Cuộc trò chuyện mới",
    sessions: "Lịch sử",
    today: "Hôm nay",
    yesterday: "Hôm qua",
    this_week: "Tuần này",
    earlier: "Trước đó",
    server_info: "Thông tin Server",
    channels: "Kênh",
    roles: "Vai trò",
    members: "Thành viên",
    structure: "Cấu trúc",
    audit_log: "Nhật ký",
    send: "Gửi",
    approve: "Duyệt",
    reject: "Từ chối",
    login_title: "Đăng nhập bằng Discord",
    login_desc: "Quản lý server Discord bằng AI",
    logout: "Đăng xuất",
    select_server: "Chọn server...",
    admin_panel: "Quản trị",
    update_key: "Cập nhật API Key",
    no_sessions: "Chưa có cuộc trò chuyện nào",
    type_message: "Nhập tin nhắn...",
    pending_approval: "Chờ duyệt",
    plan_steps: "bước",
    risk_level: "Rủi ro",
    clarify_title: "Cần thêm thông tin",
    loading: "Đang tải...",
    lang_toggle: "EN",
  }
};

function setLang(lang) {
  localStorage.setItem('lang', lang);
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (I18N[lang][key]) {
      if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
        el.placeholder = I18N[lang][key];
      } else {
        el.textContent = I18N[lang][key];
      }
    }
  });
  // Update lang toggle button text
  document.getElementById('langBtn').textContent = I18N[lang].lang_toggle;
}
```

### HTML pattern:
```html
<button data-i18n="approve">Approve</button>
<span data-i18n="channels">Channels</span>
<input data-i18n="type_message" placeholder="Type a message...">
```

---

## 2. No Emoji Icons — Use Text/CSS Instead

### Replace all emoji with styled elements:

| Old | New |
|-----|-----|
| ✅ Duyệt | `<button class="btn-approve">Approve</button>` (green bg) |
| ❌ Từ chối | `<button class="btn-reject">Reject</button>` (red bg) |
| 🔄 Refresh | `<button class="btn-icon"><svg>↻</svg></button>` |
| 📁 Category | `<span class="tree-icon folder"></span>` (CSS triangle) |
| # channel | `<span class="tree-icon channel-text"></span>` |
| 🔊 voice | `<span class="tree-icon channel-voice"></span>` |
| ⚙️ Admin | `<span class="section-title">Admin Panel</span>` (no emoji) |

### Button styles:
```css
.btn-approve { 
  background: var(--success); color: #fff; 
  border: none; border-radius: var(--radius-sm);
  padding: 6px 14px; font-size: 13px; font-weight: 500; cursor: pointer;
}
.btn-reject { 
  background: var(--danger); color: #fff;
  border: none; border-radius: var(--radius-sm);
  padding: 6px 14px; font-size: 13px; font-weight: 500; cursor: pointer;
}
```

---

## 3. Streaming Responses

### Web Dashboard (SSE — Server-Sent Events):

**Backend** (`api_routes.py`):
```python
from fastapi.responses import StreamingResponse

@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    async def generate():
        async for chunk in planner_service.generate_stream(req.message, req.guild_id, req.user_id):
            yield f"data: {json.dumps(chunk)}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")
```

**Frontend** (EventSource-like fetch):
```javascript
async function sendMessageStream(message) {
  const msgDiv = appendBotMessage(''); // Empty bubble
  
  const response = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({message, guild_id, user_id})
  });
  
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  
  while (true) {
    const {done, value} = await reader.read();
    if (done) break;
    
    buffer += decoder.decode(value, {stream: true});
    const lines = buffer.split('\n');
    buffer = lines.pop(); // Keep incomplete line
    
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6);
        if (data === '[DONE]') break;
        const chunk = JSON.parse(data);
        if (chunk.type === 'text') {
          msgDiv.innerHTML = marked.parse(msgDiv._rawText = (msgDiv._rawText || '') + chunk.content);
        } else if (chunk.type === 'status') {
          // Show status indicator (planning, executing, etc.)
        } else if (chunk.type === 'approval') {
          // Render approval card
        } else if (chunk.type === 'clarify') {
          // Render clarify card
        }
      }
    }
  }
}
```

### Discord Bot (typing indicator + chunked send):

```python
# In discord_bot.py message handler:
async with message.channel.typing():
    result = await process_request(message)

# For long responses, send partial updates:
# 1. Initial "thinking" message
thinking_msg = await message.channel.send("Processing your request...")

# 2. Update with streaming chunks (edit message every ~500ms)
# Discord rate limit: 5 edits per 5 seconds
# Strategy: buffer chunks, edit every 1 second
```

**Discord limitation**: Discord API doesn't support true SSE to clients.
Best approach:
1. Show typing indicator (`async with channel.typing()`)
2. Send initial embed "Planning..." 
3. Edit embed progressively as steps complete
4. Final response when done

---

## 4. Smooth Page Transitions

### Approach: CSS transitions + view switching (no page reloads)

```css
/* Fade transition for content switching */
.view-container {
  opacity: 1;
  transition: opacity 0.15s ease;
}
.view-container.switching {
  opacity: 0;
}

/* Slide transition for panels */
.right-panel {
  transform: translateX(0);
  transition: transform 0.2s ease, width 0.2s ease;
}
.right-panel.collapsed {
  transform: translateX(100%);
  width: 0;
  overflow: hidden;
}

/* Session switch animation */
.chat-messages {
  transition: opacity 0.12s ease;
}
.chat-messages.loading {
  opacity: 0.5;
}
```

### Session loading (no full page reload):
```javascript
async function loadSession(sessionId) {
  const chatEl = document.getElementById('chatMessages');
  chatEl.classList.add('loading');
  
  const data = await fetch(`/api/sessions/${sessionId}/history`).then(r => r.json());
  
  // Small delay for smooth transition feel
  await new Promise(r => setTimeout(r, 100));
  
  renderMessages(data.history);
  chatEl.classList.remove('loading');
  
  // Update active session in sidebar
  document.querySelectorAll('.session-item').forEach(el => el.classList.remove('active'));
  document.querySelector(`[data-session="${sessionId}"]`)?.classList.add('active');
}
```

### Login → Dashboard transition:
- After OAuth callback, redirect to `/dashboard` with a CSS fade-in on `<body>`
```css
body { animation: fadeIn 0.3s ease; }
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
```

---

## 5. Streaming Chunk Protocol

### Unified chunk format (backend → frontend):
```json
// Text chunk (streaming LLM response)
{"type": "text", "content": "partial text here"}

// Status update
{"type": "status", "status": "planning", "message": "Creating execution plan..."}
{"type": "status", "status": "executing", "message": "Running step 1/3..."}

// Plan ready (for approval)
{"type": "approval", "plan_id": "uuid", "summary": "...", "steps": [...], "risk": "MEDIUM"}

// Clarify needed
{"type": "clarify", "summary": "...", "questions": ["...", "..."]}

// Completion
{"type": "done", "final_message": "All steps completed successfully."}

// Error
{"type": "error", "message": "Something went wrong."}
```

---

## 6. Files to Modify

| File | Changes |
|------|---------|
| `frontend/templates/dashboard.html` | Full rewrite with i18n, no emoji, streaming |
| `frontend/templates/login.html` | English default, i18n attrs, fade transition |
| `frontend/templates/callback.html` | Minimal — just redirect with animation |
| `frontend/static/style.css` | Add transition classes, btn-approve/reject, tree-icons |
| `app/interfaces/api_routes.py` | Add `/api/chat/stream` SSE endpoint |
| `app/services/planner_service.py` | Add `generate_stream()` method (yields chunks) |
| `app/interfaces/discord_bot.py` | Typing indicator + progressive message edit |

---

## 7. Priority Order

1. i18n system (affects all pages — do first)
2. Dashboard rewrite (layout + no emoji + streaming client)
3. Login/callback pages (minimal — just i18n + animation)
4. Backend streaming endpoint
5. Discord streaming (typing + progressive edit)
