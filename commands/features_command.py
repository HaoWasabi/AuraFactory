import json
import nextcord
from nextcord.ext import commands
from tools.discord_features import DiscordFeatures 

class FeaturesCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="setup_verify")
    async def setup_verify_cmd(self, ctx: commands.Context, channel_id: int, role_id: int, emoji: str, title: str, *, description: str):
        """
        Lệnh: !setup_verify <id_kênh> <id_role> <emoji> <tiêu_đề> <mô_tả>
        """
        if not ctx.guild:
            return await ctx.send("Lệnh này chỉ có thể dùng trong Server.")

        await ctx.send("⏳ Đang thiết lập hệ thống xác minh thành viên...")
        
        result = await DiscordFeatures.setup_verification_system(
            guild=ctx.guild,
            channel_id=channel_id,
            role_id=role_id,
            emoji=emoji,
            title=title,
            description=description
        )
        await ctx.send(f"```json\n{result}\n```")


    @commands.command(name="config_autodel")
    async def config_autodel_cmd(self, ctx: commands.Context, channel_id: int, delay_seconds: int):
        """
        Lệnh: !config_autodel <id_kênh> <số_giây_chờ>
        """
        if not ctx.guild:
            return await ctx.send("Lệnh này chỉ có thể dùng trong Server.")

        await ctx.send(f"⏳ Đang cấu hình tự động xóa tin nhắn cho kênh `{channel_id}`...")
        
        result = await DiscordFeatures.configure_auto_delete(
            guild=ctx.guild,
            channel_id=channel_id,
            delay_seconds=delay_seconds
        )
        await ctx.send(f"```json\n{result}\n```")


    @commands.command(name="create_poll")
    async def create_poll_cmd(self, ctx: commands.Context, channel_id: int, question: str, *, options_str: str):
        """
        Lệnh: !create_poll <id_kênh> "Câu hỏi" Lựa chọn 1 | Lựa chọn 2 | Lựa chọn 3
        """
        if not ctx.guild:
            return await ctx.send("Lệnh này chỉ có thể dùng trong Server.")

        # Tách các tùy chọn bằng dấu gạch đứng | và loại bỏ khoảng trắng thừa
        options = [opt.strip() for opt in options_str.split("|") if opt.strip()]

        await ctx.send("⏳ Đang khởi tạo bảng bỏ phiếu bình chọn...")
        
        result = await DiscordFeatures.create_interactive_poll(
            guild=ctx.guild,
            channel_id=channel_id,
            question=question,
            options=options
        )
        await ctx.send(f"```json\n{result}\n```")


    @commands.command(name="setup_welcome")
    async def setup_welcome_cmd(self, ctx: commands.Context, channel_id: int, welcome_title: str, *, welcome_template: str):
        """
        Lệnh: !setup_welcome <id_kênh> "Tiêu đề" Nội dung template chứa {member} và {guild}
        """
        if not ctx.guild:
            return await ctx.send("Lệnh này chỉ có thể dùng trong Server.")

        await ctx.send("⏳ Đang thiết lập hệ thống và gửi tin nhắn chào mừng mẫu...")
        
        result = await DiscordFeatures.setup_welcome_system(
            guild=ctx.guild,
            channel_id=channel_id,
            welcome_title=welcome_title,
            welcome_message_template=welcome_template
        )
        await ctx.send(f"```json\n{result}\n```")

# Đăng ký cog vào bot
def setup(bot: commands.Bot):
    bot.add_cog(FeaturesCommand(bot))