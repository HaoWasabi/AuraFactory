# tools/discord_management.py
import json
import nextcord
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Union

class DiscordMember:
    """
    Tập hợp các bộ công cụ (Tools) dành cho Agentic AI đóng vai trò làm "Quản trị viên ảo" (Virtual Moderator),
    giúp tự động hóa việc kiểm soát thành viên, làm sạch kênh chat và điều hành máy chủ.
    """

    @staticmethod
    async def kick_member(guild: nextcord.Guild, member_id: int, reason: Optional[str] = "Được yêu cầu bởi AI Agent") -> str:
        """
        Công cụ trục xuất (Kick) một thành viên ra khỏi máy chủ.
        """
        try:
            member = guild.get_member(member_id) or await guild.fetch_member(member_id)
            if not member:
                return json.dumps({"status": "error", "message": "Không tìm thấy thành viên này trong máy chủ."}, ensure_ascii=False)

            # Kiểm tra phân cấp quyền: Bot không thể kick người có chức vụ cao hơn hoặc bằng nó, hoặc chủ server
            if member.top_role >= guild.me.top_role or member.id == guild.owner_id:
                return json.dumps({"status": "error", "message": "Không thể kick thành viên này do phân cấp quyền (Họ là Chủ server hoặc có Vai trò cao hơn Bot)."}, ensure_ascii=False)

            member_name = member.name
            await member.kick(reason=reason)

            return json.dumps({
                "status": "success",
                "action": "kick",
                "member_id": member_id,
                "member_name": member_name,
                "reason": reason
            }, ensure_ascii=False)

        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot thiếu quyền 'Kick Members' hoặc Vai trò của Bot xếp dưới Vai trò của đối tượng."}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Thất bại khi thực hiện lệnh kick: {str(e)}"}, ensure_ascii=False)

    @staticmethod
    async def ban_member(guild: nextcord.Guild, member_id: int, delete_message_seconds: int = 0, reason: Optional[str] = "Được yêu cầu bởi AI Agent") -> str:
        """
        Công cụ cấm (Ban) một thành viên khỏi máy chủ, hỗ trợ xóa tin nhắn cũ của họ.
        - delete_message_seconds: Số giây tin nhắn cũ của user đó cần xóa (Discord hỗ trợ tối đa 7 ngày = 604800 giây).
        """
        try:
            # Tìm trong guild trước, nếu họ đã thoát/bị kick trước đó thì dùng fetch_user để ban từ xa
            member = guild.get_member(member_id)
            if member:
                if member.top_role >= guild.me.top_role or member.id == guild.owner_id:
                    return json.dumps({"status": "error", "message": "Không thể ban thành viên này do phân cấp quyền (Họ là Chủ server hoặc có Vai trò cao hơn Bot)."}, ensure_ascii=False)
                member_name = member.name
            else:
                # Tìm user từ hệ thống Discord nếu họ không có trong server
                try:
                    user = await guild.files_bot.fetch_user(member_id) if hasattr(guild, 'files_bot') else None
                    # Fallback thông thường nếu không lấy được bot instance
                    user = await guild.me.roles[0].guild.files_bot.fetch_user(member_id) if not user else user
                    member_name = user.name if user else f"User ID: {member_id}"
                except:
                    member_name = f"User ID: {member_id}"

            await guild.ban(nextcord.Object(id=member_id), delete_message_seconds=delete_message_seconds, reason=reason)

            return json.dumps({
                "status": "success",
                "action": "ban",
                "member_id": member_id,
                "member_name": member_name,
                "delete_message_seconds": delete_message_seconds,
                "reason": reason
            }, ensure_ascii=False)

        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot thiếu quyền 'Ban Members' hoặc mục tiêu có cấp bậc cao hơn Bot."}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Thất bại khi thực hiện lệnh ban: {str(e)}"}, ensure_ascii=False)

    @staticmethod
    async def unban_member(guild: nextcord.Guild, member_id: int, reason: Optional[str] = "Được yêu cầu bởi AI Agent") -> str:
        """
        Công cụ gỡ cấm (Unban) cho một thành viên bằng ID của họ.
        """
        try:
            # Tạo một đối tượng Object giả lập chứa ID để unban mà không cần tìm User đầy đủ
            user_obj = nextcord.Object(id=member_id)
            await guild.unban(user_obj, reason=reason)

            return json.dumps({
                "status": "success",
                "action": "unban",
                "member_id": member_id,
                "reason": reason
            }, ensure_ascii=False)

        except nextcord.NotFound:
            return json.dumps({"status": "error", "message": "Thành viên này không nằm trong danh sách bị cấm (Ban List) của Server."}, ensure_ascii=False)
        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot thiếu quyền 'Ban Members' để thực hiện gỡ cấm."}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Thất bại khi unban: {str(e)}"}, ensure_ascii=False)

    @staticmethod
    async def timeout_member(guild: nextcord.Guild, member_id: int, duration_minutes: int, reason: Optional[str] = "Được yêu cầu bởi AI Agent") -> str:
        """
        Công cụ cấm túc (Timeout/Mute) thành viên vi phạm quy định trong một khoảng thời gian (phút).
        Truyền duration_minutes = 0 để gỡ timeout trước thời hạn.
        """
        try:
            member = guild.get_member(member_id) or await guild.fetch_member(member_id)
            if not member:
                return json.dumps({"status": "error", "message": "Không tìm thấy thành viên trên Server."}, ensure_ascii=False)

            if member.top_role >= guild.me.top_role or member.id == guild.owner_id:
                return json.dumps({"status": "error", "message": "Không thể cấm túc thành viên này do phân cấp quyền hệ thống."}, ensure_ascii=False)

            if duration_minutes > 0:
                # Tính toán mốc thời gian cấm túc
                delta = timedelta(minutes=duration_minutes)
                await member.timeout(delta, reason=reason)
                action_name = "timeout"
            else:
                # Nếu truyền bằng 0 hoặc nhỏ hơn, tiến hành gỡ timeout
                await member.timeout(None, reason=reason)
                action_name = "untimeout"

            return json.dumps({
                "status": "success",
                "action": action_name,
                "member_id": member_id,
                "member_name": member.name,
                "duration_minutes": duration_minutes,
                "reason": reason
            }, ensure_ascii=False)

        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot thiếu quyền 'Moderate Members' để thực hiện cấm túc đối tượng này."}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Thất bại khi xử lý timeout: {str(e)}"}, ensure_ascii=False)

    @staticmethod
    async def purge_messages(guild: nextcord.Guild, channel_id: int, limit: int = 100, **kwargs) -> str:
        """
        Công cụ dọn dẹp, xóa hàng loạt tin nhắn rác/tin nhắn cũ trong một kênh chat (Purge).
        Hỗ trợ qua kwargs:
          - member_id: Chỉ xóa tin nhắn của một thành viên cụ thể (Lọc tin nhắn spam).
        """
        try:
            channel = guild.get_channel(channel_id)
            if not channel or not isinstance(channel, nextcord.TextChannel):
                return json.dumps({"status": "error", "message": "Không tìm thấy kênh văn bản hoặc ID truyền vào không phải kênh chat chữ."}, ensure_ascii=False)

            target_member_id = kwargs.pop('member_id', None)
            deleted_count = 0

            # Xây dựng hàm check điều kiện lọc tin nhắn nếu Agent yêu cầu chỉ xóa của 1 người cụ thể
            def check_condition(msg):
                if target_member_id:
                    return msg.author.id == target_member_id
                return True

            # Thực thi xóa tin nhắn hàng loạt theo điều kiện lọc
            deleted_messages = await channel.purge(limit=limit, check=check_condition)
            deleted_count = len(deleted_messages)

            return json.dumps({
                "status": "success",
                "action": "purge",
                "channel_id": channel_id,
                "channel_name": channel.name,
                "requested_limit": limit,
                "actually_deleted_count": deleted_count,
                "filtered_by_member_id": target_member_id
            }, ensure_ascii=False)

        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot thiếu quyền 'Manage Messages' hoặc 'Read Message History' tại kênh này."}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Thất bại khi dọn dẹp tin nhắn: {str(e)}"}, ensure_ascii=False)

    @staticmethod
    async def modify_member_nickname(guild: nextcord.Guild, member_id: int, new_nickname: Optional[str] = None, reason: Optional[str] = "Được yêu cầu bởi AI Agent") -> str:
        """
        Công cụ thay đổi biệt danh (Nickname) của một thành viên trên Server.
        Truyền new_nickname = None hoặc chuỗi rỗng để xóa biệt danh (Reset về tên gốc).
        """
        try:
            member = guild.get_member(member_id) or await guild.fetch_member(member_id)
            if not member:
                return json.dumps({"status": "error", "message": "Không tìm thấy thành viên."}, ensure_ascii=False)

            # Phân cấp: Bot chỉ sửa được nick của người có role thấp hơn nó (Trừ khi tự sửa nick của chính mình)
            if member.id != guild.me.id and member.top_role >= guild.me.top_role:
                return json.dumps({"status": "error", "message": "Không thể đổi biệt danh của người có cấp bậc cao hơn hoặc bằng Bot."}, ensure_ascii=False)

            # Tiến hành chỉnh sửa biệt danh
            nick_to_set = None if not new_nickname or new_nickname.strip() == "" else new_nickname
            await member.edit(nick=nick_to_set, reason=reason)

            return json.dumps({
                "status": "success",
                "action": "modify_nickname",
                "member_id": member_id,
                "old_name_or_nick": member.display_name,
                "new_nickname": nick_to_set if nick_to_set else "Đã reset về tên gốc",
                "reason": reason
            }, ensure_ascii=False)

        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot thiếu quyền 'Manage Nicknames' (hoặc quyền 'Change Nickname' nếu tự sửa nick của Bot)."}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Lỗi đổi biệt danh: {str(e)}"}, ensure_ascii=False)