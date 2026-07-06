# app/tools/discord/templates.py
"""
Discord Server Template Tools.
Apply pre-built workspace templates to quickly set up entire server structure.
"""
from typing import Dict, Any, List, Optional
import asyncio
import nextcord


# === Pre-built Templates ===

TEMPLATES = {
    "gaming_community": {
        "name": "Gaming Community",
        "description": "Server chuẩn cho cộng đồng gaming",
        "categories": [
            {
                "name": "📌 THÔNG BÁO",
                "channels": [
                    {"name": "luật-server", "type": "text", "topic": "Nội quy server — đọc trước khi chat"},
                    {"name": "thông-báo", "type": "text", "topic": "Thông báo quan trọng từ Admin"},
                    {"name": "cập-nhật", "type": "text", "topic": "Cập nhật mới từ game/server"},
                ],
            },
            {
                "name": "💬 CHUNG",
                "channels": [
                    {"name": "tán-gẫu", "type": "text", "topic": "Chat tự do"},
                    {"name": "giới-thiệu", "type": "text", "topic": "Giới thiệu bản thân"},
                    {"name": "meme", "type": "text", "topic": "Chia sẻ meme vui"},
                ],
            },
            {
                "name": "🎮 GAME",
                "channels": [
                    {"name": "tìm-team", "type": "text", "topic": "Tìm đội chơi cùng"},
                    {"name": "tips-tricks", "type": "text", "topic": "Chia sẻ mẹo chơi game"},
                    {"name": "screenshot", "type": "text", "topic": "Khoe ảnh gameplay"},
                ],
            },
            {
                "name": "🔊 VOICE",
                "channels": [
                    {"name": "Lobby", "type": "voice"},
                    {"name": "Team 1", "type": "voice"},
                    {"name": "Team 2", "type": "voice"},
                    {"name": "AFK", "type": "voice"},
                ],
            },
        ],
        "roles": [
            {"name": "Admin", "color": "#E74C3C", "permissions": ["administrator"]},
            {"name": "Moderator", "color": "#E67E22", "permissions": ["manage_messages", "kick_members", "mute_members"]},
            {"name": "Member", "color": "#3498DB", "permissions": []},
            {"name": "Newcomer", "color": "#95A5A6", "permissions": []},
        ],
    },
    "study_group": {
        "name": "Study Group / Học tập",
        "description": "Server cho nhóm học tập, CLB, lớp học",
        "categories": [
            {
                "name": "📌 THÔNG TIN",
                "channels": [
                    {"name": "nội-quy", "type": "text", "topic": "Nội quy nhóm học"},
                    {"name": "thông-báo", "type": "text", "topic": "Lịch học, deadline, thay đổi"},
                    {"name": "tài-liệu", "type": "text", "topic": "Upload tài liệu học tập"},
                ],
            },
            {
                "name": "📚 HỌC TẬP",
                "channels": [
                    {"name": "thảo-luận-chung", "type": "text", "topic": "Thảo luận bài học"},
                    {"name": "hỏi-đáp", "type": "forum", "topic": "Đặt câu hỏi & nhận trả lời"},
                    {"name": "chia-sẻ-kiến-thức", "type": "text", "topic": "Chia sẻ bài viết, video hay"},
                ],
            },
            {
                "name": "📝 BÀI TẬP",
                "channels": [
                    {"name": "bài-tập-tuần", "type": "text", "topic": "Bài tập hàng tuần"},
                    {"name": "nộp-bài", "type": "text", "topic": "Upload bài làm"},
                    {"name": "review-code", "type": "forum", "topic": "Code review lẫn nhau"},
                ],
            },
            {
                "name": "🔊 PHÒNG HỌC",
                "channels": [
                    {"name": "Phòng học nhóm", "type": "voice"},
                    {"name": "Thuyết trình", "type": "stage"},
                    {"name": "Tự học im lặng", "type": "voice"},
                ],
            },
            {
                "name": "☕ GIẢI TRÍ",
                "channels": [
                    {"name": "off-topic", "type": "text", "topic": "Chat ngoài lề"},
                    {"name": "nhạc", "type": "voice"},
                ],
            },
        ],
        "roles": [
            {"name": "Giảng viên", "color": "#9B59B6", "permissions": ["manage_messages", "manage_channels"]},
            {"name": "Trợ giảng", "color": "#1ABC9C", "permissions": ["manage_messages"]},
            {"name": "Sinh viên", "color": "#3498DB", "permissions": []},
        ],
    },
    "startup_team": {
        "name": "Startup / Team dự án",
        "description": "Server cho team startup hoặc dự án phần mềm",
        "categories": [
            {
                "name": "📌 GENERAL",
                "channels": [
                    {"name": "announcements", "type": "text", "topic": "Company updates"},
                    {"name": "general", "type": "text", "topic": "General discussion"},
                    {"name": "standup", "type": "text", "topic": "Daily standup updates"},
                ],
            },
            {
                "name": "💻 ENGINEERING",
                "channels": [
                    {"name": "dev-frontend", "type": "text", "topic": "Frontend development"},
                    {"name": "dev-backend", "type": "text", "topic": "Backend development"},
                    {"name": "dev-ops", "type": "text", "topic": "DevOps & Infrastructure"},
                    {"name": "code-review", "type": "forum", "topic": "PRs & code review requests"},
                    {"name": "bugs", "type": "forum", "topic": "Bug reports & tracking"},
                ],
            },
            {
                "name": "📊 BUSINESS",
                "channels": [
                    {"name": "product", "type": "text", "topic": "Product discussions & roadmap"},
                    {"name": "marketing", "type": "text", "topic": "Marketing & growth"},
                    {"name": "customer-feedback", "type": "forum", "topic": "Customer feedback & insights"},
                ],
            },
            {
                "name": "🔊 MEETINGS",
                "channels": [
                    {"name": "Daily Standup", "type": "voice"},
                    {"name": "Sprint Planning", "type": "voice"},
                    {"name": "1-on-1", "type": "voice"},
                    {"name": "All Hands", "type": "stage"},
                ],
            },
            {
                "name": "🔒 LEADERSHIP",
                "channels": [
                    {"name": "leadership", "type": "text", "topic": "Leadership team only", "private": True},
                    {"name": "hiring", "type": "text", "topic": "Recruitment discussions", "private": True},
                ],
            },
        ],
        "roles": [
            {"name": "Founder", "color": "#E74C3C", "permissions": ["administrator"]},
            {"name": "Lead", "color": "#E67E22", "permissions": ["manage_channels", "manage_messages"]},
            {"name": "Engineer", "color": "#3498DB", "permissions": []},
            {"name": "Designer", "color": "#9B59B6", "permissions": []},
            {"name": "Marketing", "color": "#1ABC9C", "permissions": []},
        ],
    },
}


async def apply_server_template(
    guild: nextcord.Guild,
    template_name: str,
    clear_existing: bool = False,
    reason: str = "AI Agent — Apply Template",
) -> Dict[str, Any]:
    """
    Apply a pre-built template to the server.
    
    Args:
        template_name: Key from TEMPLATES dict
        clear_existing: If True, delete existing channels/categories first (DANGEROUS)
    """
    if template_name not in TEMPLATES:
        return {
            "success": False,
            "error": f"Template '{template_name}' not found. Available: {list(TEMPLATES.keys())}",
        }

    template = TEMPLATES[template_name]
    results = {"categories_created": 0, "channels_created": 0, "roles_created": 0, "errors": []}

    # Optionally clear existing structure
    if clear_existing:
        for channel in guild.channels:
            try:
                await channel.delete(reason=f"{reason} — clearing for template")
                await asyncio.sleep(0.5)  # Rate limit protection
            except Exception:
                pass

    # Create roles first
    for role_def in template.get("roles", []):
        try:
            color = nextcord.Color(int(role_def.get("color", "#000000").lstrip("#"), 16))
            
            # Build permissions
            perms = nextcord.Permissions.none()
            for perm_name in role_def.get("permissions", []):
                if hasattr(perms, perm_name):
                    setattr(perms, perm_name, True)

            # Check if role exists
            existing = nextcord.utils.get(guild.roles, name=role_def["name"])
            if not existing:
                await guild.create_role(
                    name=role_def["name"],
                    color=color,
                    permissions=perms,
                    reason=reason,
                )
                results["roles_created"] += 1
            await asyncio.sleep(0.3)
        except Exception as e:
            results["errors"].append(f"Role '{role_def['name']}': {e}")

    # Create categories and channels
    for cat_def in template.get("categories", []):
        try:
            # Check if category exists
            category = nextcord.utils.get(guild.categories, name=cat_def["name"])
            if not category:
                category = await guild.create_category(name=cat_def["name"], reason=reason)
                results["categories_created"] += 1
            await asyncio.sleep(0.3)

            # Create channels in category
            for ch_def in cat_def.get("channels", []):
                try:
                    ch_type = ch_def.get("type", "text")
                    ch_name = ch_def["name"]

                    # Check if channel exists in category
                    existing = nextcord.utils.get(category.channels, name=ch_name.lower().replace(" ", "-"))
                    if existing:
                        continue

                    if ch_type == "text":
                        await category.create_text_channel(
                            name=ch_name,
                            topic=ch_def.get("topic", ""),
                            reason=reason,
                        )
                    elif ch_type == "voice":
                        await category.create_voice_channel(
                            name=ch_name,
                            reason=reason,
                        )
                    elif ch_type == "forum":
                        await category.create_forum_channel(
                            name=ch_name,
                            topic=ch_def.get("topic", ""),
                            reason=reason,
                        )
                    elif ch_type == "stage":
                        await category.create_stage_channel(
                            name=ch_name,
                            reason=reason,
                        )

                    results["channels_created"] += 1
                    await asyncio.sleep(0.3)  # Rate limit protection
                except Exception as e:
                    results["errors"].append(f"Channel '{ch_def['name']}': {e}")

        except Exception as e:
            results["errors"].append(f"Category '{cat_def['name']}': {e}")

    return {
        "success": True,
        "template": template_name,
        "template_description": template["description"],
        **results,
    }


def list_templates() -> Dict[str, Any]:
    """List all available server templates."""
    templates_info = []
    for key, tmpl in TEMPLATES.items():
        templates_info.append({
            "key": key,
            "name": tmpl["name"],
            "description": tmpl["description"],
            "categories": len(tmpl.get("categories", [])),
            "roles": len(tmpl.get("roles", [])),
            "total_channels": sum(
                len(cat.get("channels", [])) for cat in tmpl.get("categories", [])
            ),
        })
    return {"success": True, "templates": templates_info}
