# tools/discord_category.py
import json
import nextcord
from typing import Optional, List, Dict, Any, Union

class DiscordCategory:
    """
    Tập hợp các bộ công cụ (Tools) tối ưu hóa riêng cho Agentic AI nhằm quản lý,
    tạo, sửa, và đồng bộ cấu hình Danh mục (Category) trên hệ thống Discord.
    """

    @staticmethod
    def _build_category_overwrites(guild: nextcord.Guild, kwargs: Dict[str, Any]) -> Optional[Dict[Any, nextcord.PermissionOverwrite]]:
        """Helper tự động build ma trận phân quyền nâng cao cho Danh mục giống như hệ thống Kênh"""
        is_private = kwargs.pop('is_private', False)
        allowed_role_ids = kwargs.pop('allowed_role_ids', [])
        allowed_user_ids = kwargs.pop('allowed_user_ids', [])
        advanced_permissions = kwargs.pop('advanced_permissions', None)

        if not is_private and not advanced_permissions:
            return None

        overwrites = {}
        custom_overwrite = nextcord.PermissionOverwrite()
        
        # Đọc cấu hình quyền nâng cao (ví dụ: khóa gửi tin nhắn, khóa kết nối...)
        if advanced_permissions:
            for perm, val in advanced_permissions.items():
                if hasattr(custom_overwrite, perm): 
                    setattr(custom_overwrite, perm, val)

        if is_private:
            # Khóa quyền xem danh mục của toàn bộ thành viên thông thường
            overwrites[guild.default_role] = nextcord.PermissionOverwrite(view_channel=False)
            setattr(custom_overwrite, "view_channel", True)
            
            # Cấp quyền xem cho các vai trò VIP được chỉ định
            for r_id in allowed_role_ids:
                role = guild.get_role(r_id)
                if role: 
                    overwrites[role] = custom_overwrite if advanced_permissions else nextcord.PermissionOverwrite(view_channel=True)
                    
            # Cấp quyền xem cho các thành viên đích danh
            for u_id in allowed_user_ids:
                member = guild.get_member(u_id)
                if member: 
                    overwrites[member] = custom_overwrite if advanced_permissions else nextcord.PermissionOverwrite(view_channel=True)
        else:
            if advanced_permissions:
                overwrites[guild.default_role] = custom_overwrite

        # Luôn giữ quyền tối thượng cho Bot để tránh Agent vô tình khóa Bot
        overwrites[guild.me] = nextcord.PermissionOverwrite(view_channel=True, manage_channels=True)
        return overwrites

    @staticmethod
    async def create_category(guild: nextcord.Guild, category_name: str, **kwargs) -> str:
        """
        Công cụ tạo một Danh mục (Category) mới với toàn bộ cấu hình vị trí và phân quyền nâng cao.
        Hỗ trợ các tham số qua kwargs: position, is_private, allowed_role_ids, allowed_user_ids, advanced_permissions
        """
        try:
            # Xử lý phân quyền tự động từ kwargs
            overwrites = DiscordCategory._build_category_overwrites(guild, kwargs)
            if overwrites: 
                kwargs['overwrites'] = overwrites

            # Khởi tạo danh mục bằng cách rải tham số động vào hàm của Nextcord
            category = await guild.create_category(name=category_name, **kwargs)
            
            return json.dumps({
                "status": "success",
                "action": "create_category",
                "category_name": category.name,
                "category_id": category.id,
                "position": category.position
            }, ensure_ascii=False)

        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot thiếu quyền 'Manage Channels' để tạo Danh mục."}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Thất bại khi tạo Danh mục: {str(e)}"}, ensure_ascii=False)

    @staticmethod
    async def modify_category(guild: nextcord.Guild, category_id: int, **kwargs) -> str:
        """
        Công cụ chỉnh sửa các thuộc tính nâng cao của một Danh mục hiện tại (Đổi tên, Đổi vị trí, Sửa quyền).
        Hỗ trợ các tham số qua kwargs: new_name, position, update_permissions
        """
        try:
            category = guild.get_channel(category_id)
            if not category or not isinstance(category, nextcord.CategoryChannel):
                return json.dumps({"status": "error", "message": "Không tìm thấy ID Danh mục hoặc ID này không phải là một Category."}, ensure_ascii=False)

            # Chuẩn hóa tên tham số từ định dạng Agent sang chuẩn hàm Nextcord
            if 'new_name' in kwargs: 
                kwargs['name'] = kwargs.pop('new_name')
                
            update_permissions = kwargs.pop('update_permissions', None)

            # Lọc an toàn các trường dữ liệu mà CategoryChannel thực sự hỗ trợ
            valid_kwargs = {}
            for key, val in kwargs.items():
                if val is not None and hasattr(category, key):
                    valid_kwargs[key] = val

            # Xử lý cập nhật quyền động cho một Role/User cụ thể trong danh mục
            if update_permissions:
                target_id = update_permissions.get("target_id")
                target = guild.get_role(target_id) or guild.get_member(target_id)
                if target:
                    overwrite_obj = category.overwrites_for(target)
                    for p_key, p_val in update_permissions.get("permissions", {}).items():
                        if hasattr(overwrite_obj, p_key): 
                            setattr(overwrite_obj, p_key, p_val)
                    await category.set_permissions(target, overwrite=overwrite_obj)

            # Thực thi chỉnh sửa một loạt
            if valid_kwargs:
                await category.edit(**valid_kwargs)

            return json.dumps({
                "status": "success",
                "action": "modify_category",
                "category_id": category_id,
                "updated_fields": list(valid_kwargs.keys()) + (["permissions"] if update_permissions else [])
            }, ensure_ascii=False)

        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot thiếu quyền chỉnh sửa Danh mục này."}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Lỗi chỉnh sửa Danh mục: {str(e)}"}, ensure_ascii=False)

    @staticmethod
    async def sync_all_channels_in_category(guild: nextcord.Guild, category_id: int) -> str:
        """
        Công cụ ép buộc TẤT CẢ các kênh con nằm bên trong Danh mục phải đồng bộ quyền hạn 
        theo cấu hình quyền của Danh mục cha (Rất hữu ích sau khi sửa quyền của Category).
        """
        try:
            category = guild.get_channel(category_id)
            if not category or not isinstance(category, nextcord.CategoryChannel):
                return json.dumps({"status": "error", "message": "Danh mục không tồn tại hoặc không hợp lệ."}, ensure_ascii=False)

            synced_channels = []
            # Duyệt qua toàn bộ kênh con thuộc danh mục này
            for channel in category.channels:
                await channel.edit(sync_permissions=True)
                synced_channels.append(channel.name)

            return json.dumps({
                "status": "success",
                "action": "sync_category_channels",
                "category_id": category_id,
                "synced_channels_count": len(synced_channels),
                "synced_channels": synced_channels
            }, ensure_ascii=False)

        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot thiếu quyền 'Manage Channels' hoặc 'Manage Roles' để đồng bộ."}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Thất bại khi đồng bộ: {str(e)}"}, ensure_ascii=False)