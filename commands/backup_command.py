import json
import aiohttp
import nextcord
from nextcord.ext import commands
from tools.discord_backup import DiscordBackup

class BackupCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="export_server")
    async def export_server_cmd(self, ctx: commands.Context):
        """
        Lệnh: !export_server
        Tự động kiểm tra độ dài dữ liệu cấu trúc để trả về văn bản hoặc File .json đính kèm.
        """
        if not ctx.guild:
            return await ctx.send("❌ Lệnh này chỉ có thể dùng trong Server.")

        await ctx.send("⏳ Đang tiến hành quét phân tích toàn bộ hạ tầng Server...")
        
        result = await DiscordBackup.export_server_structure(ctx.guild)
        
        # Kiểm tra xem kết quả trả về là Object File đính kèm hay là Chuỗi text thông thường
        if isinstance(result, nextcord.File):
            await ctx.send("📦 Server có cấu trúc lớn! Hệ thống đã đóng gói hạ tầng thành file an toàn:", file=result)
        else:
            await ctx.send(f"```json\n{result}\n```")


    @commands.command(name="restore_server")
    async def restore_server_cmd(self, ctx: commands.Context):
        """
        Lệnh: !restore_server (Hãy đính kèm/upload kèm theo 1 file backup.json khi gõ lệnh này)
        """
        if not ctx.guild:
            return await ctx.send("❌ Lệnh này chỉ có thể dùng trong Server.")

        # Kiểm tra xem người dùng có tải file đính kèm lên cùng tin nhắn chat không
        if not ctx.message.attachments:
            return await ctx.send("❌ Thiếu file dữ liệu! Vui lòng upload đính kèm file `.json` sao lưu cùng với lệnh này.")

        attachment = ctx.message.attachments[0]
        if not attachment.filename.endswith('.json'):
            return await ctx.send("❌ Vui lòng đính kèm file định dạng `.json` hợp lệ.")

        await ctx.send("⏳ Đang đọc tải tệp cấu hình sao lưu...")
        
        try:
            # Đọc bytes trực tiếp từ link file đính kèm thông qua bộ nhớ đệm
            file_bytes = await attachment.read()
            backup_dict = json.loads(file_bytes.decode('utf-8'))
        except Exception as e:
            return await ctx.send(f"❌ Lỗi định dạng đọc tệp JSON: {str(e)}")

        await ctx.send("🚀 Khởi chạy trình khôi phục cấu trúc. Đã kích hoạt hệ thống chống nghẽn Rate Limit (Vui lòng đợi)...")
        
        # Đưa Dictionary đã giải nén an toàn vào bộ xử lý phục hồi hạ tầng
        result = await DiscordBackup.restore_server_structure(guild=ctx.guild, backup_data_dict=backup_dict)
        await ctx.send(f"```json\n{result}\n```")

def setup(bot: commands.Bot):
    bot.add_cog(BackupCommand(bot))