# tools/discord_role.py
import json
import nextcord
from typing import Optional, List, Dict, Any, Union

class DiscordRole:
    """
    Tập hợp các bộ công cụ (Tools) tối ưu hóa riêng cho Agentic AI nhằm quản lý,
    tạo, sửa, xóa, gán và sao chép Vai trò (Roles) trên hệ thống Discord.
    """

    @staticmethod
    def _parse_permissions(permissions_dict: Dict[str, bool]) -> nextcord.Permissions:
        """Helper để chuyển đổi cấu hình JSON/Dict quyền của Agent thành Object Permissions của Nextcord"""
        perms = nextcord.Permissions.none()
        for perm_name, value in permissions_dict.items():
            if hasattr(perms, perm_name) and isinstance(value, bool):
                setattr(perms, perm_name, value)
        return perms

    @staticmethod
    def _permissions_to_dict(perms: nextcord.Permissions) -> Dict[str, bool]:
        """Helper để chuyển đổi Object Permissions của Nextcord thành Dict/JSON sạch cho Agent đọc"""
        return {perm_name: value for perm_name, value in perms if value is True}

    @staticmethod
    async def create_role(guild: nextcord.Guild, role_name: str, **kwargs) -> str:
        """
        Công cụ tạo một Vai trò (Role) mới với đầy đủ thuộc tính nâng cao.
        Hỗ trợ qua kwargs: 
          - color: Mã màu Hex (str), ví dụ: "#ff0000" hoặc số nguyên mã màu (int)
          - hoist: Bật/Tắt hiển thị tách biệt thành viên có role này trên danh sách (bool)
          - mentionable: Cho phép mọi người tag @role này hay không (bool)
          - permissions: Dict chứa các quyền cụ thể, ví dụ: {"kick_members": True, "send_messages": True}
        """
        try:
            # 1. Xử lý chuẩn hóa màu sắc từ Agent (Nếu Agent truyền chuỗi dạng "#FFFFFF")
            if 'color' in kwargs and isinstance(kwargs['color'], str):
                color_str = kwargs['color'].lstrip('#')
                kwargs['color'] = nextcord.Color(int(color_str, 16))
            elif 'color' in kwargs and isinstance(kwargs['color'], int):
                kwargs['color'] = nextcord.Color(kwargs['color'])

            # 2. Xử lý bộ dịch quyền từ Dict sang Object hệ thống
            if 'permissions' in kwargs and isinstance(kwargs['permissions'], dict):
                kwargs['permissions'] = DiscordRole._parse_permissions(kwargs['permissions'])

            # 3. Tạo Role bằng cách rải kwargs động vào Nextcord
            role = await guild.create_role(name=role_name, **kwargs)

            return json.dumps({
                "status": "success",
                "action": "create_role",
                "role_name": role.name,
                "role_id": role.id,
                "color": str(role.color),
                "hoist": role.hoist,
                "mentionable": role.mentionable
            }, ensure_ascii=False)

        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot thiếu quyền 'Manage Roles' (hoặc quyền này cao hơn vị trí của Bot) để tạo Role."}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Thất bại khi tạo Role: {str(e)}"}, ensure_ascii=False)

    @staticmethod
    async def modify_role(guild: nextcord.Guild, role_id: int, **kwargs) -> str:
        """
        Công cụ chỉnh sửa linh hoạt bất kỳ thuộc tính nào của một Role hiện tại.
        Hỗ trợ qua kwargs: new_name, color, hoist, mentionable, permissions (Dict[str, bool]), position (vị trí cấp bậc)
        """
        try:
            role = guild.get_role(role_id)
            if not role:
                return json.dumps({"status": "error", "message": "Không tìm thấy ID Vai trò trong Server."}, ensure_ascii=False)

            # Kiểm tra xem quyền cấp bậc của Bot có đủ cao để sửa Role này không
            if role >= guild.me.top_role:
                return json.dumps({"status": "error", "message": "Không thể chỉnh sửa Role này vì cấp bậc của nó cao hơn hoặc bằng Vai trò cao nhất của Bot."}, ensure_ascii=False)

            # Chuẩn hóa các tham số đầu vào từ file test của bạn sang chuẩn Nextcord
            if 'new_name' in kwargs:
                kwargs['name'] = kwargs.pop('new_name')

            if 'color' in kwargs and isinstance(kwargs['color'], str):
                kwargs['color'] = nextcord.Color(int(kwargs['color'].lstrip('#'), 16))

            if 'permissions' in kwargs and isinstance(kwargs['permissions'], dict):
                # Lấy quyền hiện tại ra, cập nhật đè các quyền mới lên để tránh mất quyền cũ không nhắc tới
                current_perms = role.permissions
                for p_key, p_val in kwargs['permissions'].items():
                    if hasattr(current_perms, p_key):
                        setattr(current_perms, p_key, p_val)
                kwargs['permissions'] = current_perms

            # Tách riêng 'position' vì thay đổi vị trí cấp bậc (Hierarchy) cần dùng hàm khác của Nextcord
            position = kwargs.pop('position', None)
            if position is not None:
                await role.edit(position=position)

            # Lọc an toàn các trường dữ liệu mà Role thực sự hỗ trợ sửa đổi trực tiếp
            valid_kwargs = {}
            for key, val in kwargs.items():
                if val is not None and hasattr(role, key):
                    valid_kwargs[key] = val

            if valid_kwargs:
                await role.edit(**valid_kwargs)

            return json.dumps({
                "status": "success",
                "action": "modify_role",
                "role_id": role_id,
                "updated_fields": list(valid_kwargs.keys()) + (["position"] if position is not None else [])
            }, ensure_ascii=False)

        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot bị từ chối quyền chỉnh sửa Vai trò này."}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Lỗi chỉnh sửa Role: {str(e)}"}, ensure_ascii=False)

    @staticmethod
    async def delete_role(guild: nextcord.Guild, role_id: int, reason: str = "Được yêu cầu bởi AI Agent") -> str:
        """
        Công cụ xóa bỏ một Vai trò ra khỏi server.
        """
        try:
            role = guild.get_role(role_id)
            if not role:
                return json.dumps({"status": "error", "message": "Không tìm thấy vai trò cần xóa."}, ensure_ascii=False)

            if role >= guild.me.top_role or role.is_default():
                return json.dumps({"status": "error", "message": "Không thể xóa Role này (Role @everyone mặc định hoặc cấp bậc cao hơn Bot)."}, ensure_ascii=False)

            role_name = role.name
            await role.delete(reason=reason)

            return json.dumps({
                "status": "success",
                "action": "delete_role",
                "role_id": role_id,
                "role_name": role_name
            }, ensure_ascii=False)

        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot thiếu quyền 'Manage Roles' để xóa."}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Thất bại khi xóa: {str(e)}"}, ensure_ascii=False)

    @staticmethod
    async def assign_role_to_member(guild: nextcord.Guild, member_id: int, role_id: int) -> str:
        """
        Công cụ gán một Vai trò cho một Thành viên cụ thể.
        """
        try:
            member = guild.get_member(member_id) or await guild.fetch_member(member_id)
            role = guild.get_role(role_id)

            if not member or not role:
                return json.dumps({"status": "error", "message": "Không tìm thấy Thành viên hoặc Vai trò yêu cầu trên Server."}, ensure_ascii=False)

            if role >= guild.me.top_role:
                return json.dumps({"status": "error", "message": "Bot không thể gán Role này vì nó có cấp bậc cao hơn hoặc bằng vai trò cao nhất của Bot."}, ensure_ascii=False)

            await member.add_roles(role)
            return json.dumps({
                "status": "success",
                "action": "assign_role",
                "member_name": member.name,
                "role_name": role.name
            }, ensure_ascii=False)

        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot thiếu quyền cấp vai trò (Manage Roles)."}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Thất bại khi gán role: {str(e)}"}, ensure_ascii=False)

    @staticmethod
    async def remove_role_from_member(guild: nextcord.Guild, member_id: int, role_id: int) -> str:
        """
        Công cụ gỡ một Vai trò ra khỏi một Thành viên.
        """
        try:
            member = guild.get_member(member_id) or await guild.fetch_member(member_id)
            role = guild.get_role(role_id)

            if not member or not role:
                return json.dumps({"status": "error", "message": "Không tìm thấy Thành viên hoặc Vai trò."}, ensure_ascii=False)

            if role >= guild.me.top_role:
                return json.dumps({"status": "error", "message": "Bot không thể gỡ Role này do phân cấp phân quyền hệ thống."}, ensure_ascii=False)

            await member.remove_roles(role)
            return json.dumps({
                "status": "success",
                "action": "remove_role",
                "member_name": member.name,
                "role_name": role.name
            }, ensure_ascii=False)

        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot thiếu quyền gỡ vai trò."}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Lỗi thực thi gỡ role: {str(e)}"}, ensure_ascii=False)

    @staticmethod
    async def clone_role(guild: nextcord.Guild, source_role_id: int, target_role_name: str) -> str:
        """
        Công cụ sao chép vai trò (Clone Role) - Copy 100% màu sắc, quyền hạn, hiển thị 
        từ một Role có sẵn sang một Role mới tinh với tên mới. (Tương ứng lệnh @sao_chep_vai_tro)
        """
        try:
            source_role = guild.get_role(source_role_id)
            if not source_role:
                return json.dumps({"status": "error", "message": "Không tìm thấy vai trò gốc để sao chép."}, ensure_ascii=False)

            # Khởi tạo role mới nhân bản toàn bộ thuộc tính cơ bản và ma trận quyền
            new_role = await guild.create_role(
                name=target_role_name,
                permissions=source_role.permissions,
                color=source_role.color,
                hoist=source_role.hoist,
                mentionable=source_role.mentionable
            )

            return json.dumps({
                "status": "success",
                "action": "clone_role",
                "source_role_name": source_role.name,
                "new_role_name": new_role.name,
                "new_role_id": new_role.id
            }, ensure_ascii=False)

        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot thiếu quyền 'Manage Roles' để sao chép nhân bản."}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Lỗi nhân bản vai trò: {str(e)}"}, ensure_ascii=False)

    @staticmethod
    async def get_role_permissions_info(guild: nextcord.Guild, role_id: int) -> str:
        """
        Công cụ kiểm tra quyền (Tương ứng với lệnh @hien_thi_quyen). 
        Trả về danh sách các quyền đang được BẬT (True) dưới dạng danh sách JSON sạch cho Agent đọc.
        """
        try:
            role = guild.get_role(role_id)
            if not role:
                return json.dumps({"status": "error", "message": "Không tìm thấy vai trò."}, ensure_ascii=False)

            active_permissions = DiscordRole._permissions_to_dict(role.permissions)

            return json.dumps({
                "status": "success",
                "role_name": role.name,
                "role_id": role.id,
                "active_permissions_count": len(active_permissions),
                "active_permissions": active_permissions
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Lỗi lấy thông tin quyền: {str(e)}"}, ensure_ascii=False)