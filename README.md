# AuraFactory
Quản lý dự án: Trương Gia Hào

### Tổng quan:
- Tên dự án: AuraFactory - Hệ thống Agentic AI tự động hóa thiết lập hạ tầng không gian số trên nền tảng Discord.
- Ý tưởng cốt lõi: Discord là nền tảng giao tiếp mạnh mẽ nhờ cơ chế đa kênh và phân quyền (Roles/Permissions) hiệu quả, đang được nhiều cộng đồng và doanh nghiệp dùng làm không gian làm việc nội bộ. AuraFactory ra đời nhằm tối ưu hóa và tự động hóa toàn bộ quy trình thiết lập Workspace, phân quyền, quản lý thành viên và tích hợp Chatbot thông minh thông qua các AI Agent, giảm tải tối đa công việc cho Admin.
- Core Flow: Admin đưa ra yêu cầu bằng ngôn ngữ tự nhiên -> Agentic AI lập kế hoạch -> Gọi Discord API/Bot để thực thi.

### Cấu trúc thư mực
```
discord_agentic_system/
├── config/                  # Cấu hình hệ thống & Khóa bảo mật
│   ├── settings.py          # Load env (DISCORD_TOKEN, OPENAI_API_KEY, DB_URL,...)
│   └── prompts.py           # Lưu trữ các System Prompts tối mật cho từng Agent
│
├── core/                    # Đầu não kết nối và điều phối
│   ├── bot.py               # Gateway kết nối Discord (Nhận lệnh từ User và chuyển cho AI)
│   └── orchestrator.py      # LLM Agent Orchestrator (Nhận diện ý định, lập kế hoạch, gọi Agent)
│
├── agents/                  # Tập hợp các AI Agents chuyên biệt (Brain)
│   ├── __init__.py
│   ├── base_agent.py        # Lớp cha định nghĩa cấu trúc một Agent
│   ├── architect_agent.py   # Agent Kiến trúc sư (Phân tích yêu cầu, thiết kế sơ đồ server)
│   ├── moderator_agent.py   # Agent Giám sát & Bảo mật (Tự động tạo luật, cấu hình AutoMod)
│   └── DevOps_agent.py      # Agent Triển khai (Xây dựng, cấu hình quyền, kết nối Webhook)
│
├── tools/                   # Các công cụ/kỹ năng mà Agent có thể sử dụng (Action)
│   ├── __init__.py
│   ├── discord_server.py    # Tool sửa server
│   ├── discord_channel.py   # Tool tạo/xóa/sửa Kênh, Danh mục (Category)
│   ├── discord_role.py      # Tool thiết lập ma trận quyền, phân vai trò (Roles)
│   ├── discord_member.py    # Tool quản lý thành viên (Kick, Ban, Timeout, Purge)
│   ├── discord_features.py  # Tool cấu hình tiện ích (Xác minh, Chào mừng, Auto-delete)
│   ├── discord_backup.py    # Tool sao lưu & khôi phục cấu trúc Server
│   ├── discord_webhook.py   # Tool cấu hình tích hợp, kết nối GitHub/GitLab
│   └── web_search.py        # Tool tìm kiếm template server mẫu trên mạng (nếu cần)
│
├── memory/                  # Bộ nhớ và RAG (Kiến thức hạ tầng)
│   ├── __init__.py
│   ├── vector_store.py      # Kết nối Vector Database (Chroma, Pinecone) lưu mẫu thiết kế
│   └── context_manager.py   # Quản lý bộ nhớ hội thoại ngắn hạn (Short-term memory)
│
├── utils/                   # Các hàm bổ trợ
│   ├── logger.py            # Ghi log chi tiết các bước suy nghĩ của Agent (Chain of Thought)
│   └── templates/           # Các file JSON/YAML chứa template server mẫu chuẩn hóa
│
├── tests/                   # Kịch bản kiểm thử tự động cho Agent
├── .env                     # Biến môi trường bảo mật
├── README.md                # Tài liệu hệ thống
└── requirements.txt         # Thư viện (disnake/nextcord, langchain/langgraph, openai, chromadb...)
```
