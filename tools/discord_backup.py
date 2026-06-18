# tools/discord_backup.py
import json
import nextcord
from typing import Optional, Dict, Any, List

class DiscordBackup:
    """
    Tập hợp các bộ công cụ (Tools) dành cho Agentic AI nhằm Sao lưu (Export) 
    và Khôi phục (Import/Restore) toàn bộ cấu trúc hạ tầng cấu hình của Máy chủ Discord.
    """

    @staticmethod
    def _export_overwrites(channel: nextcord.abc.GuildChannel) -> List[Dict[str, Any]]:
        """Helper biến đổi ma trận quyền overwrites của một kênh thành cấu trúc danh sách dict/JSON"""
        serialized = []
        for target, overwrite in channel.overwrites.items():
            # Xác định đối tượng được áp quyền là Vai trò (Role) hay Thành viên (Member)
            target_type = "role" if isinstance(target, nextcord.Role) else "member"
            
            # Lọc lấy các quyền đang được tùy chỉnh (Bật True hoặc Khóa False, bỏ qua kế thừa None)
            perm_dict = {}
            for perm_name, value in overwrite:
                if value is not None:
                    perm_dict[perm_name] = value

            if perm_dict:
                serialized.append({
                    "target_name": target.name,
                    "target_type": target_type,
                    "is_everyone": isinstance(target, nextcord.Role) and target.is_default(),
                    "permissions": perm_dict
                })
        return serialized

    @staticmethod
    async def export_server_structure(guild: nextcord.Guild) -> str:
        """
        Công cụ quét toàn bộ Server hiện tại và đóng gói cấu trúc thành chuỗi JSON sạch (Backup).
        Sao lưu: Tên server, Mức độ bảo mật, Danh sách Roles (màu, quyền), Categories và Kênh con.
        """
        try:
            backup_data = {
                "server_name": guild.name,
                "verification_level": str(guild.verification_level),
                "roles": [],
                "categories": [],
                "standalone_channels": [] # Kênh không nằm trong danh mục nào
            }

            # 1. Quét và lưu cấu trúc Vai trò (Roles) - Sắp xếp theo cấp bậc từ thấp đến cao
            for role in sorted(guild.roles, key=lambda r: r.position):
                if role.is_default(): # Ghi nhận cấu hình của role @everyone mặc định
                    backup_data["roles"].append({
                        "name": "@everyone",
                        "is_everyone": True,
                        "permissions": {name: val for name, val in role.permissions if val is True}
                    })
                    continue
                
                # Bỏ qua các role hệ thống của Bot khác tạo ra tự động
                if role.managed:
                    continue

                backup_data["roles"].append({
                    "name": role.name,
                    "is_everyone": False,
                    "color": f"#{role.color.value:06x}" if role.color.value != 0 else None,
                    "hoist": role.hoist,
                    "mentionable": role.mentionable,
                    "permissions": {name: val for name, val in role.permissions if val is True}
                })

            # 2. Quét và lưu cấu trúc Danh mục (Categories) cùng các kênh con bên trong chúng
            for category in guild.categories:
                category_info = {
                    "name": category.name,
                    "overwrites": DiscordBackupTools._export_overwrites(category),
                    "channels": []
                }

                # Quét các kênh con thuộc danh mục này
                for channel in category.channels:
                    channel_type = "text" if isinstance(channel, nextcord.TextChannel) else "voice" if isinstance(channel, nextcord.VoiceChannel) else "forum" if isinstance(channel, nextcord.ForumChannel) else "stage"
                    
                    chan_data = {
                        "name": channel.name,
                        "type": channel_type,
                        "overwrites": DiscordBackupTools._export_overwrites(channel)
                    }
                    # Bổ sung thuộc tính đặc trưng tùy loại kênh
                    if channel_type == "text":
                        chan_data["topic"] = channel.topic
                        chan_data["slowmode_delay"] = channel.slowmode_delay
                        chan_data["nsfw"] = channel.nsfw
                    elif channel_type == "voice":
                        chan_data["user_limit"] = channel.user_limit
                        chan_data["bitrate"] = channel.bitrate

                    category_info["channels"].append(chan_data)

                backup_data["categories"].append(category_info)

            # 3. Quét các kênh mồ côi (Standalone) không nằm trong Danh mục nào
            for channel in guild.channels:
                if channel.category_id is None and not isinstance(channel, nextcord.CategoryChannel):
                    channel_type = "text" if isinstance(channel, nextcord.TextChannel) else "voice" if isinstance(channel, nextcord.VoiceChannel) else "stage"
                    chan_data = {
                        "name": channel.name,
                        "type": channel_type,
                        "overwrites": DiscordBackupTools._export_overwrites(channel)
                    }
                    if channel_type == "text":
                        chan_data["topic"] = channel.topic
                    backup_data["standalone_channels"].append(chan_data)

            return json.dumps(backup_data, ensure_ascii=False, indent=4)

        except Exception as e:
            return json.dumps({"status": "error", "message": f"Thất bại khi xuất cấu trúc cấu hình: {str(e)}"}, ensure_ascii=False)

    @staticmethod
    async def restore_server_structure(guild: nextcord.Guild, backup_json_str: str) -> str:
        """
        Công cụ đọc chuỗi JSON cấu trúc và tự động dựng lại toàn bộ Server (Restore/Import).
        Tự động map ma trận quyền overwrites sang các ID Role mới được tạo ra trên Server mới.
        """
        try:
            # Kiểm tra quyền tối cao của Bot trước khi dựng hạ tầng
            if not guild.me.guild_permissions.administrator:
                return json.dumps({"status": "error", "message": "Bot bắt buộc phải có quyền 'Administrator' để thực hiện Khôi phục hạ tầng cấu trúc máy chủ."}, ensure_ascii=False)

            data = json.loads(backup_json_str)
            role_mapping = {guild.default_role.name: guild.default_role} # Lưu vết: {"Tên Role Cũ": Đối tượng Role Mới tạo}

            # 1. Khôi phục/Tạo lại hệ thống Vai trò (Roles)
            for r_data in data.get("roles", []):
                if r_data.get("is_everyone", False):
                    # Cập nhật quyền cho role @everyone hiện tại của Server mới
                    perms = nextcord.Permissions.none()
                    for p_name, p_val in r_data.get("permissions", {}).items():
                        if hasattr(perms, p_name): setattr(perms, p_name, p_val)
                    await guild.default_role.edit(permissions=perms)
                    continue

                # Tạo mới Role thường
                perms = nextcord.Permissions.none()
                for p_name, p_val in r_data.get("permissions", {}).items():
                    if hasattr(perms, p_name): setattr(perms, p_name, p_val)

                color_hex = r_data.get("color")
                color = nextcord.Color(int(color_hex.lstrip('#'), 16)) if color_hex else nextcord.Color.default()

                new_role = await guild.create_role(
                    name=r_data["name"],
                    permissions=perms,
                    color=color,
                    hoist=r_data.get("hoist", False),
                    mentionable=r_data.get("mentionable", False)
                )
                role_mapping[new_role.name] = new_role

            # Hàm cục bộ Helper để dịch tên Role trong JSON thành cấu hình Overwrite thực tế của Discord
            def build_overwrites_dict(ow_list: List[Dict[str, Any]]) -> Dict[Any, nextcord.PermissionOverwrite]:
                overwrites = {}
                for ow in ow_list:
                    if ow["target_type"] == "role":
                        # Khớp nối tìm Role mới dựa trên Tên Role cũ đã sao lưu
                        role_obj = guild.default_role if ow.get("is_everyone") else role_mapping.get(ow["target_name"])
                        if role_obj:
                            overwrite_obj = nextcord.PermissionOverwrite()
                            for p_name, p_val in ow["permissions"].items():
                                if hasattr(overwrite_obj, p_name): setattr(overwrite_obj, p_name, p_val)
                            overwrites[role_obj] = overwrite_obj
                return overwrites

            # 2. Khôi phục/Tạo lại hệ thống Danh mục (Categories) và Kênh con
            for cat_data in data.get("categories", []):
                cat_overwrites = build_overwrites_dict(cat_data.get("overwrites", []))
                
                # Tạo Danh mục cha
                new_category = await guild.create_category(name=cat_data["name"], overwrites=cat_overwrites)

                # Tạo các kênh con đặt bên trong Danh mục cha đó
                for ch_data in cat_data.get("channels", []):
                    ch_overwrites = build_overwrites_dict(ch_data.get("overwrites", []))
                    c_type = ch_data["type"]

                    if c_type == "text":
                        await guild.create_text_channel(
                            name=ch_data["name"],
                            category=new_category,
                            overwrites=ch_overwrites,
                            topic=ch_data.get("topic"),
                            slowmode_delay=ch_data.get("slowmode_delay", 0),
                            nsfw=ch_data.get("nsfw", False)
                        )
                    elif c_type == "voice":
                        await guild.create_voice_channel(
                            name=ch_data["name"],
                            category=new_category,
                            overwrites=ch_overwrites,
                            user_limit=ch_data.get("user_limit", 0),
                            bitrate=ch_data.get("bitrate", 64000)
                        )

            # 3. Khôi phục/Tạo lại hệ thống Kênh mồ côi (Standalone)
            for ch_data in data.get("standalone_channels", []):
                ch_overwrites = build_overwrites_dict(ch_data.get("overwrites", []))
                if ch_data["type"] == "text":
                    await guild.create_text_channel(name=ch_data["name"], overwrites=ch_overwrites, topic=ch_data.get("topic"))
                elif ch_data["type"] == "voice":
                    await guild.create_voice_channel(name=ch_data["name"], overwrites=ch_overwrites)

            return json.dumps({
                "status": "success",
                "action": "restore_server",
                "message": "Toàn bộ cấu trúc hạ tầng máy chủ đã được thiết lập khôi phục thành công rực rỡ!",
                "roles_created": len(role_mapping) - 1,
                "categories_created": len(data.get("categories", []))
            }, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"status": "error", "message": f"Quá trình khôi phục gặp lỗi hệ thống: {str(e)}"}, ensure_ascii=False)