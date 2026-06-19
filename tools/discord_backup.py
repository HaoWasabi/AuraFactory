import json
import asyncio
import io
import nextcord
from typing import Optional, Dict, Any, List, Union

class DiscordBackup:
    """
    Tập hợp các bộ công cụ (Tools) tối ưu hóa nâng cao dành cho Agentic AI 
    nhằm Sao lưu (Export) và Khôi phục (Restore) hạ tầng cấu hình Máy chủ Discord,
    chống nghẽn Rate Limit và tự động đóng gói File đính kèm chống tràn ký tự tin nhắn.
    """

    @staticmethod
    def _export_overwrites(channel: nextcord.abc.GuildChannel) -> List[Dict[str, Any]]:
        """Helper biến đổi ma trận quyền overwrites của một kênh thành cấu trúc danh sách dict/JSON"""
        serialized = []
        for target, overwrite in channel.overwrites.items():
            target_type = "role" if isinstance(target, nextcord.Role) else "member"
            
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
    async def export_server_structure(guild: nextcord.Guild) -> Union[str, nextcord.File]:
        """
        Công cụ quét toàn bộ hạ tầng Server hiện tại.
        - Nếu cấu trúc ngắn gọn: Trả về chuỗi JSON thông thường.
        - Nếu cấu trúc quá dài: Tự động đóng gói thành một nextcord.File để Agent gửi thẳng lên Discord channel.
        """
        try:
            backup_data = {
                "server_name": guild.name,
                "verification_level": str(guild.verification_level),
                "roles": [],
                "categories": [],
                "standalone_channels": []
            }

            # 1. Quét và lưu cấu trúc Vai trò (Roles)
            for role in sorted(guild.roles, key=lambda r: r.position):
                if role.is_default():
                    backup_data["roles"].append({
                        "name": "@everyone",
                        "is_everyone": True,
                        "permissions": {name: val for name, val in role.permissions if val is True}
                    })
                    continue
                
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

            # 2. Quét Danh mục (Categories) và kênh con
            for category in guild.categories:
                category_info = {
                    "name": category.name,
                    "overwrites": DiscordBackup._export_overwrites(category),
                    "channels": []
                }

                for channel in category.channels:
                    channel_type = "text" if isinstance(channel, nextcord.TextChannel) else "voice" if isinstance(channel, nextcord.VoiceChannel) else "forum" if isinstance(channel, nextcord.ForumChannel) else "stage"
                    
                    chan_data = {
                        "name": channel.name,
                        "type": channel_type,
                        "overwrites": DiscordBackup._export_overwrites(channel)
                    }
                    if channel_type == "text":
                        chan_data["topic"] = channel.topic
                        chan_data["slowmode_delay"] = channel.slowmode_delay
                        chan_data["nsfw"] = channel.nsfw
                    elif channel_type == "voice":
                        chan_data["user_limit"] = channel.user_limit
                        chan_data["bitrate"] = channel.bitrate

                    category_info["channels"].append(chan_data)
                backup_data["categories"].append(category_info)

            # 3. Quét kênh mồ côi (Standalone)
            for channel in guild.channels:
                if channel.category_id is None and not isinstance(channel, nextcord.CategoryChannel):
                    channel_type = "text" if isinstance(channel, nextcord.TextChannel) else "voice" if isinstance(channel, nextcord.VoiceChannel) else "stage"
                    chan_data = {
                        "name": channel.name,
                        "type": channel_type,
                        "overwrites": DiscordBackup._export_overwrites(channel)
                    }
                    if channel_type == "text":
                        chan_data["topic"] = channel.topic
                    backup_data["standalone_channels"].append(chan_data)

            final_json = json.dumps(backup_data, ensure_ascii=False, indent=4)
            
            # Khắc phục Giới hạn 2000 ký tự chat: Nếu chuỗi dài quá, nén vào luồng Bytes để tạo File Đính Kèm
            if len(final_json) > 1900:
                file_stream = io.BytesIO(final_json.encode('utf-8'))
                return nextcord.File(fp=file_stream, filename=f"backup_{guild.id}.json")
            
            return final_json

        except Exception as e:
            return json.dumps({"status": "error", "message": f"Thất bại khi xuất cấu trúc: {str(e)}"}, ensure_ascii=False)

    @staticmethod
    async def restore_server_structure(guild: nextcord.Guild, backup_data_dict: Dict[str, Any]) -> str:
        """
        Công cụ đọc Dictionary dữ liệu cấu trúc và tự động dựng lại Server.
        Đã tích hợp cơ chế giãn cách Asyncio Sleep thông minh chống dính tịt Rate Limit từ Discord.
        """
        try:
            if not guild.me.guild_permissions.administrator:
                return json.dumps({"status": "error", "message": "Bot bắt buộc phải có quyền 'Administrator' để thực hiện."}, ensure_ascii=False)

            role_mapping = {guild.default_role.name: guild.default_role}
            
            # Bộ đếm hỗ trợ tính toán giãn cách (Cứ mỗi 5 thao tác API nặng, cho Bot nghỉ 1.5 giây để hồi luồng)
            api_request_counter = 0

            async def rate_limit_gate():
                nonlocal api_request_counter
                api_request_counter += 1
                if api_request_counter % 5 == 0:
                    await asyncio.sleep(1.5)

            # 1. Khôi phục hệ thống Vai trò (Roles)
            for r_data in backup_data_dict.get("roles", []):
                await rate_limit_gate()
                if r_data.get("is_everyone", False):
                    perms = nextcord.Permissions.none()
                    for p_name, p_val in r_data.get("permissions", {}).items():
                        if hasattr(perms, p_name): setattr(perms, p_name, p_val)
                    await guild.default_role.edit(permissions=perms)
                    continue

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

            # Helper map đè ma trận quyền
            def build_overwrites_dict(ow_list: List[Dict[str, Any]]) -> Dict[Any, nextcord.PermissionOverwrite]:
                overwrites = {}
                for ow in ow_list:
                    if ow["target_type"] == "role":
                        role_obj = guild.default_role if ow.get("is_everyone") else role_mapping.get(ow["target_name"])
                        if role_obj:
                            overwrite_obj = nextcord.PermissionOverwrite()
                            for p_name, p_val in ow["permissions"].items():
                                if hasattr(overwrite_obj, p_name): setattr(overwrite_obj, p_name, p_val)
                            overwrites[role_obj] = overwrite_obj
                return overwrites

            # 2. Khôi phục hệ thống Danh mục (Categories) và Kênh con
            for cat_data in backup_data_dict.get("categories", []):
                await rate_limit_gate()
                cat_overwrites = build_overwrites_dict(cat_data.get("overwrites", []))
                new_category = await guild.create_category(name=cat_data["name"], overwrites=cat_overwrites)

                for ch_data in cat_data.get("channels", []):
                    await rate_limit_gate()
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

            # 3. Khôi phục hệ thống Kênh mồ côi (Standalone)
            for ch_data in backup_data_dict.get("standalone_channels", []):
                await rate_limit_gate()
                ch_overwrites = build_overwrites_dict(ch_data.get("overwrites", []))
                if ch_data["type"] == "text":
                    await guild.create_text_channel(name=ch_data["name"], overwrites=ch_overwrites, topic=ch_data.get("topic"))
                elif ch_data["type"] == "voice":
                    await guild.create_voice_channel(name=ch_data["name"], overwrites=ch_overwrites)

            return json.dumps({
                "status": "success",
                "action": "restore_server",
                "message": "Cấu trúc hạ tầng máy chủ đã được thiết lập khôi phục thành công (An toàn Rate limit)!",
                "roles_created": len(role_mapping) - 1,
                "categories_created": len(backup_data_dict.get("categories", []))
            }, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"status": "error", "message": f"Quá trình khôi phục gặp lỗi: {str(e)}"}, ensure_ascii=False)