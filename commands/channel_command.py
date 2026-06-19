import json
import nextcord
from nextcord.ext import commands
from tools.discord_channel import DiscordChannel 

class ChannelCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="create_ch")
    async def create_ch_cmd(self, ctx: commands.Context, channel_name: str, channel_type: str, *, json_kwargs: str = "{}"):
        """
        Lệnh: !create_ch <tên_kênh> <loại_kênh> [chuỗi_json_cấu_hình]
        """
        if not ctx.guild:
            return await ctx.send("Lệnh này chỉ có thể dùng trong Server (Guild).")

        try:
            kwargs = json.loads(json_kwargs)
        except json.JSONDecodeError:
            return await ctx.send("❌ Định dạng cấu hình phụ (JSON) không hợp lệ.")

        await ctx.send(f"⏳ Đang tạo kênh `{channel_name}` (Loại: `{channel_type}`)...")
        
        # Gọi trực tiếp hàm public từ lớp DiscordChannel
        result = await DiscordChannel.create_channel(
            guild=ctx.guild, 
            channel_name=channel_name, 
            channel_type=channel_type, 
            **kwargs
        )
        
        await ctx.send(f"```json\n{result}\n```")


    @commands.command(name="modify_ch")
    async def modify_ch_cmd(self, ctx: commands.Context, channel_id: int, *, json_kwargs: str):
        """
        Lệnh: !modify_ch <id_kênh> <chuỗi_json_cấu_hình>
        """
        if not ctx.guild:
            return await ctx.send("Lệnh này chỉ có thể dùng trong Server.")

        try:
            kwargs = json.loads(json_kwargs)
        except json.JSONDecodeError:
            return await ctx.send("❌ Định dạng cấu hình phụ (JSON) không hợp lệ.")

        await ctx.send(f"⏳ Đang chỉnh sửa kênh ID `{channel_id}`...")
        
        # Gọi hàm modify_channel
        result = await DiscordChannel.modify_channel(guild=ctx.guild, channel_id=channel_id, **kwargs)
        await ctx.send(f"```json\n{result}\n```")


    @commands.command(name="delete_ch")
    async def delete_ch_cmd(self, ctx: commands.Context, target_id: int, *, reason: str = "AI Agent Request"):
        """
        Lệnh: !delete_ch <id_kênh_hoặc_danh_mục> [lý do]
        """
        if not ctx.guild:
            return await ctx.send("Lệnh này chỉ có thể dùng trong Server.")

        await ctx.send(f"⏳ Đang xóa mục tiêu ID `{target_id}`...")
        
        # Gọi hàm delete_channel_or_category
        result = await DiscordChannel.delete_channel_or_category(guild=ctx.guild, target_id=target_id, reason=reason)
        await ctx.send(f"```json\n{result}\n```")

# Đăng ký cog vào bot
def setup(bot: commands.Bot):
    bot.add_cog(ChannelCommand(bot))