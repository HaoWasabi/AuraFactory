# tools/discord_features.py
import json
import nextcord
import asyncio
from typing import Optional, List, Dict, Any, Union

class DiscordFeatures:
    """
    Tập hợp các bộ công cụ (Tools) dành cho Agentic AI nhằm cấu hình các tính năng tương tác,
    tiện ích mở rộng tự động trên Server như: Xác minh thành viên, Tự động dọn kênh, Chào mừng và Bỏ phiếu.
    """

    @staticmethod
    async def setup_verification_system(guild: nextcord.Guild, channel_id: int, role_id: int, emoji: str, title: str, description: str) -> str:
        """
        Công cụ thiết lập hệ thống xác minh tự động bằng Reaction (Reaction Verification).
        Gửi một Embed tin nhắn vào kênh được chỉ định và thả sẵn Emoji để thành viên bấm vào nhận Role.
        """
        try:
            channel = guild.get_channel(channel_id)
            role = guild.get_role(role_id)

            if not channel or not isinstance(channel, nextcord.TextChannel):
                return json.dumps({"status": "error", "message": "Không tìm thấy kênh văn bản hợp lệ để đặt hệ thống xác minh."}, ensure_ascii=False)
            if not role:
                return json.dumps({"status": "error", "message": "Không tìm thấy ID Vai trò dùng để cấp khi xác minh."}, ensure_ascii=False)
            if role >= guild.me.top_role:
                return json.dumps({"status": "error", "message": "Vai trò xác minh này cao hơn hoặc bằng Vai trò của Bot, Bot không thể cấp được."}, ensure_ascii=False)

            # 1. Tạo giao diện Embed đẹp mắt cho tin nhắn xác minh
            embed = nextcord.Embed(
                title=title,
                description=description,
                color=nextcord.Color.green()
            )
            embed.set_footer(text=f"Bấm vào biểu cảm {emoji} bên dưới để xác minh vào Server.")

            # 2. Gửi tin nhắn và tự động thả Reaction mồi
            message = await channel.send(embed=embed)
            try:
                await message.add_reaction(emoji)
            except nextcord.HTTPException:
                await message.delete()
                return json.dumps({"status": "error", "message": f"Biểu cảm '{emoji}' không hợp lệ hoặc Bot không có quyền dùng nó."}, ensure_ascii=False)

            # 3. Trả về cấu hình dữ liệu JSON sạch để code chính lưu vào verify_data.json giống file test
            return json.dumps({
                "status": "success",
                "action": "setup_verification",
                "guild_id": guild.id,
                "channel_id": channel_id,
                "message_id": message.id,
                "role_id": role_id,
                "emoji": emoji
            }, ensure_ascii=False)

        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot thiếu quyền gửi tin nhắn hoặc thêm biểu cảm tại kênh này."}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Lỗi thiết lập xác minh: {str(e)}"}, ensure_ascii=False)

    @staticmethod
    async def configure_auto_delete(guild: nextcord.Guild, channel_id: int, delay_seconds: int) -> str:
        """
        Công cụ cấu hình tính năng Tự động xóa tin nhắn sau một khoảng thời gian (Auto-delete delay).
        Phù hợp cho các kênh như lệnh bot, kênh ảnh tạm thời, hoặc phòng tìm trận (Lệnh @tu_dong_xoa).
        """
        try:
            channel = guild.get_channel(channel_id)
            if not channel or not isinstance(channel, nextcord.TextChannel):
                return json.dumps({"status": "error", "message": "Kênh văn bản không tồn tại hoặc không hợp lệ."}, ensure_ascii=False)

            # Kiểm tra quyền dọn dẹp trước khi thiết lập
            if not channel.permissions_for(guild.me).manage_messages:
                return json.dumps({"status": "error", "message": "Bot thiếu quyền 'Manage Messages' tại kênh này nên không thể bật tự động xóa."}, ensure_ascii=False)

            # Trả về tín hiệu cấu hình để Bot ghi nhận vào dictionary/bộ nhớ hệ thống
            return json.dumps({
                "status": "success",
                "action": "configure_auto_delete",
                "channel_id": channel_id,
                "channel_name": channel.name,
                "delay_seconds": delay_seconds,
                "enabled": True if delay_seconds > 0 else False
            }, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"status": "error", "message": f"Lỗi cấu hình tự động xóa: {str(e)}"}, ensure_ascii=False)

    @staticmethod
    async def create_interactive_poll(guild: nextcord.Guild, channel_id: int, question: str, options: List[str]) -> str:
        """
        Công cụ tạo một cuộc bình chọn/bỏ phiếu thông minh (Interactive Poll) hỗ trợ tối đa 10 lựa chọn.
        Tự động gắn các Emoji số từ 1️⃣ đến 🔟 làm nút bấm bình chọn cho thành viên.
        """
        try:
            channel = guild.get_channel(channel_id)
            if not channel or not isinstance(channel, nextcord.TextChannel):
                return json.dumps({"status": "error", "message": "Không tìm thấy kênh văn bản thích hợp để tạo bình chọn."}, ensure_ascii=False)

            if len(options) < 2 or len(options) > 10:
                return json.dumps({"status": "error", "message": "Số lượng tùy chọn bình chọn phải từ 2 đến 10 mục."}, ensure_ascii=False)

            emoji_numbers = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
            
            # Xây dựng nội dung danh sách lựa chọn dạng chuỗi
            poll_content = ""
            for i, option in enumerate(options):
                poll_content += f"{emoji_numbers[i]} {option}\n\n"

            # Thiết kế giao diện Embed cuộc bỏ phiếu
            embed = nextcord.Embed(
                title=f"📊 CUỘC BÌNH CHỌN: {question}",
                description=poll_content,
                color=nextcord.Color.blurple()
            )
            embed.set_footer(text="Bấm vào các biểu cảm số tương ứng bên dưới để để lại phiếu bầu của bạn.")

            poll_message = await channel.send(embed=embed)

            # Thả các reaction số tương ứng làm nút bấm
            for i in range(len(options)):
                await poll_message.add_reaction(emoji_numbers[i])

            return json.dumps({
                "status": "success",
                "action": "create_poll",
                "channel_id": channel_id,
                "message_id": poll_message.id,
                "options_count": len(options)
            }, ensure_ascii=False)

        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot thiếu quyền gửi tin nhắn hoặc thêm reaction tại kênh được chọn."}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Lỗi tạo cuộc bỏ phiếu: {str(e)}"}, ensure_ascii=False)

    @staticmethod
    async def setup_welcome_system(guild: nextcord.Guild, channel_id: int, welcome_title: str, welcome_message_template: str) -> str:
        """
        Công cụ cấu hình và kiểm tra hệ thống tin nhắn chào mừng (Welcome Message) cho Server.
        - welcome_message_template: Cho phép chứa các thẻ động như {member}, {guild} để thay thế theo thời gian thực.
        """
        try:
            channel = guild.get_channel(channel_id)
            if not channel or not isinstance(channel, nextcord.TextChannel):
                return json.dumps({"status": "error", "message": "Kênh văn bản không tồn tại hoặc không hợp lệ."}, ensure_ascii=False)

            # Gửi một tin nhắn test thử nghiệm cấu hình cho Agent và Admin xem trước diện mạo
            test_text = welcome_message_template.replace("{member}", f"@{guild.me.display_name}").replace("{guild}", guild.name)
            
            embed_test = nextcord.Embed(
                title=welcome_title,
                description=test_text,
                color=nextcord.Color.gold()
            )
            embed_test.set_footer(text="⚙️ Đây là tin nhắn cấu hình mẫu (Mọi thứ hoạt động tốt).")
            
            await channel.send(embed=embed_test)

            return json.dumps({
                "status": "success",
                "action": "setup_welcome",
                "channel_id": channel_id,
                "channel_name": channel.name,
                "title": welcome_title,
                "message_template": welcome_message_template
            }, ensure_ascii=False)

        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot không có quyền gửi tin nhắn vào kênh chào mừng được chỉ định."}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Lỗi thiết lập chào mừng: {str(e)}"}, ensure_ascii=False)