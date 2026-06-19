import json
import nextcord
from nextcord.ext import commands
from tools.discord_guild import DiscordGuild 

class GuildCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="modify_server")
    async def modify_server_cmd(self, ctx: commands.Context, *, json_kwargs: str):
        """
        Lệnh: !modify_server <chuỗi_json_cấu_hình>
        """
        if not ctx.guild:
            return await ctx.send("❌ Lệnh này chỉ có thể sử dụng trực tiếp bên trong một Server.")

        try:
            kwargs = json.loads(json_kwargs)
        except json.JSONDecodeError:
            return await ctx.send("❌ Định dạng cấu hình phụ (JSON) không hợp lệ. Vui lòng kiểm tra lại dấu ngoặc và dấu nháy.")

        await ctx.send("⏳ Đang tiến hành chỉnh sửa cấu hình hồ sơ Server...")
        
        # Gọi trực tiếp hàm static từ lớp DiscordGuild
        result = await DiscordGuild.modify_server_profile(guild=ctx.guild, **kwargs)
        
        await ctx.send(f"```json\n{result}\n```")


    @commands.command(name="server_info")
    async def server_info_cmd(self, ctx: commands.Context):
        """
        Lệnh: !server_info
        """
        if not ctx.guild:
            return await ctx.send("❌ Lệnh này chỉ có thể sử dụng trực tiếp bên trong một Server.")

        await ctx.send("⏳ Đang quét dữ liệu và kết xuất thông tin Server...")
        
        # Gọi hàm get_server_info
        result = await DiscordGuild.get_server_info(guild=ctx.guild)
        
        await ctx.send(f"```json\n{result}\n```")

# Đăng ký cog vào hệ thống bot
def setup(bot: commands.Bot):
    bot.add_cog(GuildCommand(bot))