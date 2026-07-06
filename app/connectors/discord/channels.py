# tools/discord_channel.py
import json
import nextcord
from typing import Optional, List, Dict, Any, Union

class DiscordChannel:
    """
    Bộ công cụ tối ưu hóa dựa trên luồng kiểm thử thực tế của hệ thống Agentic AI.
    """

    @staticmethod
    def _build_overwrites(guild: nextcord.Guild, kwargs: Dict[str, Any]) -> Optional[Dict[Any, nextcord.PermissionOverwrite]]:
        """Tự động bóc tách và build ma trận quyền từ kwargs để giảm tải cho hàm chính"""
        is_private = kwargs.pop('is_private', False)
        allowed_role_ids = kwargs.pop('allowed_role_ids', [])
        allowed_user_ids = kwargs.pop('allowed_user_ids', [])
        advanced_permissions = kwargs.pop('advanced_permissions', None)

        if not is_private and not advanced_permissions:
            return None

        overwrites = {}
        custom_overwrite = nextcord.PermissionOverwrite()
        if advanced_permissions:
            for perm, val in advanced_permissions.items():
                if hasattr(custom_overwrite, perm): setattr(custom_overwrite, perm, val)

        if is_private:
            overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=False)
            setattr(custom_overwrite, "view_channel", True)
            
            for r_id in allowed_role_ids:
                role = guild.get_role(r_id)
                if role: overwrites[role] = custom_overwrite if advanced_permissions else nextcord.PermissionOverwrite(view_channel=True)
                    
            for u_id in allowed_user_ids:
                member = guild.get_member(u_id)
                if member: overwrites[member] = custom_overwrite if advanced_permissions else nextcord.PermissionOverwrite(view_channel=True)
        else:
            overwrites[guild.default_role] = custom_overwrite

        overwrites[guild.me] = nextcord.PermissionOverwrite(view_channel=True, manage_channels=True)
        return overwrites

    @staticmethod
    async def create_channel(guild: nextcord.Guild, channel_name: str, channel_type: str, **kwargs) -> str:
        """
        Tối ưu bằng **kwargs: Agent có thể truyền bất kỳ tham số nâng cao nào (slowmode_delay, nsfw, user_limit...)
        Nếu không truyền, Nextcord sẽ tự dùng giá trị mặc định của Discord -> Code siêu sạch!
        """
        try:
            # 1. Trích xuất các tham số cốt lõi
            category_id = kwargs.pop('category_id', None)
            category = guild.get_channel(category_id) if category_id else None
            topic = kwargs.get('topic', None)
            
            # 2. Xử lý quyền tự động từ kwargs còn lại
            overwrites = DiscordChannel._build_overwrites(guild, kwargs)
            if overwrites: kwargs['overwrites'] = overwrites
            if category: kwargs['category'] = category

            c_type = channel_type.lower().strip()
            channel = None

            # 3. Khởi tạo kênh động bằng cách rải ngược kwargs vào hàm của Nextcord
            if c_type == "text":
                channel = await guild.create_text_channel(name=channel_name, **kwargs)
            elif c_type == "voice":
                # Tự động lọc bỏ 'topic' nếu Agent lỡ truyền nhầm vào kênh voice
                kwargs.pop('topic', None) 
                channel = await guild.create_voice_channel(name=channel_name, **kwargs)
            elif c_type == "stage":
                if "COMMUNITY" not in guild.features:
                    return json.dumps({"status": "error", "message": "Thất bại: Máy chủ phải kích hoạt tính năng 'Cộng đồng'."}, ensure_ascii=False)
                kwargs.pop('topic', None)
                channel = await guild.create_stage_channel(name=channel_name, **kwargs)
                try: await channel.create_instance(topic=topic if topic else "Welcome!")
                except Exception: pass
            elif c_type == "forum":
                channel = await guild.create_forum_channel(name=channel_name, **kwargs)
                try: await channel.create_instance(topic=topic if topic else "Welcome!")
                except Exception: pass
            elif c_type in ["news", "announcement"]:
                if "COMMUNITY" not in guild.features:
                    return json.dumps({"status": "error", "message": "Thất bại: Máy chủ phải kích hoạt tính năng 'Cộng đồng'."}, ensure_ascii=False)
                channel = await guild.create_news_channel(name=channel_name, **kwargs)
            else:
                return json.dumps({"status": "error", "message": f"Loại kênh '{channel_type}' không hợp lệ."}, ensure_ascii=False)

            # 4. Đồng bộ quyền tự động nếu là kênh công khai nằm trong mục
            if category and channel and 'overwrites' not in kwargs:
                await channel.edit(sync_permissions=True)

            return json.dumps({
                "status": "success", "action": "create_channel",
                "channel_name": channel.name, "channel_id": channel.id, "channel_type": c_type
            }, ensure_ascii=False)

        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot thiếu quyền 'Manage Channels'."}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Thất bại: {str(e)}"}, ensure_ascii=False)

    @staticmethod
    async def modify_channel(guild: nextcord.Guild, channel_id: int, **kwargs) -> str:
        """
        Tối ưu tuyệt đối cho hàm Sửa: Chỉ cần truyền những gì cần sửa qua **kwargs giống như file test của bạn.
        """
        try:
            channel = guild.get_channel(channel_id)
            if not channel:
                return json.dumps({"status": "error", "message": "Không tìm thấy ID kênh."}, ensure_ascii=False)

            # Chuẩn hóa tên tham số từ file test của bạn thành chuẩn Nextcord
            if 'new_name' in kwargs: kwargs['name'] = kwargs.pop('new_name')
            if 'new_topic' in kwargs: kwargs['topic'] = kwargs.pop('new_topic')
            
            sync_permissions = kwargs.pop('sync_permissions', False)
            update_permissions = kwargs.pop('update_permissions', None)

            # Lọc an toàn: Chỉ giữ lại các tham số mà loại kênh này THỰC SỰ HỖ TRỢ
            valid_kwargs = {}
            for key, val in kwargs.items():
                if val is not None and hasattr(channel, key):
                    valid_kwargs[key] = val

            # Xử lý đồng bộ hoặc cập nhật quyền
            if sync_permissions and channel.category:
                valid_kwargs['overwrites'] = channel.category.overwrites
            elif update_permissions:
                target = guild.get_role(update_permissions.get("target_id")) or guild.get_member(update_permissions.get("target_id"))
                if target:
                    overwrite_obj = channel.overwrites_for(target)
                    for p_key, p_val in update_permissions.get("permissions", {}).items():
                        if hasattr(overwrite_obj, p_key): setattr(overwrite_obj, p_key, p_val)
                    await channel.set_permissions(target, overwrite=overwrite_obj)

            # Thực thi chỉnh sửa một loạt bài bản
            if valid_kwargs:
                await channel.edit(**valid_kwargs)

            return json.dumps({
                "status": "success", "action": "modify_channel", 
                "channel_id": channel_id, "updated_fields": list(valid_kwargs.keys())
            }, ensure_ascii=False)
            
        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot thiếu quyền sửa kênh."}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Lỗi: {str(e)}"}, ensure_ascii=False)

    @staticmethod
    async def delete_channel_or_category(guild: nextcord.Guild, target_id: int, reason: str = "AI Agent Request") -> str:
        """Giữ nguyên cấu hình gọn gàng từ bài test của bạn"""
        try:
            channel = guild.get_channel(target_id)
            if not channel: return json.dumps({"status": "error", "message": "Mục tiêu không tồn tại."}, ensure_ascii=False)
            t_name = channel.name
            await channel.delete(reason=reason)
            return json.dumps({"status": "success", "action": "delete", "target_id": target_id, "target_name": t_name}, ensure_ascii=False)
        except nextcord.Forbidden: return json.dumps({"status": "error", "message": "Bot thiếu quyền xóa."}, ensure_ascii=False)
        except Exception as e: return json.dumps({"status": "error", "message": f"Lỗi: {str(e)}"}, ensure_ascii=False)