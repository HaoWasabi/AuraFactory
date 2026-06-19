import json
import nextcord
from nextcord.ext import commands
from tools.discord_role import DiscordRole 

class RoleCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="create_role")
    async def create_role_cmd(self, ctx: commands.Context, role_name: str, *, json_kwargs: str = "{}"):
        """
        Lệnh: !create_role <tên_role> [chuỗi_json_cấu_hình]
        """
        if not ctx.guild:
            return await ctx.send("❌ Lệnh này chỉ có thể dùng trong Server.")

        try:
            kwargs = json.loads(json_kwargs)
        except json.JSONDecodeError:
            return await ctx.send("❌ Định dạng JSON cấu hình phụ không hợp lệ. Vui lòng check lại dấu nháy đôi.")

        await ctx.send(f"⏳ Đang tiến hành khởi tạo vai trò `{role_name}`...")
        result = await DiscordRole.create_role(guild=ctx.guild, role_name=role_name, **kwargs)
        await ctx.send(f"```json\n{result}\n```")


    @commands.command(name="modify_role")
    async def modify_role_cmd(self, ctx: commands.Context, role_id: int, *, json_kwargs: str):
        """
        Lệnh: !modify_role <id_vai_trò> <chuỗi_json_chỉnh_sửa>
        """
        if not ctx.guild:
            return await ctx.send("❌ Lệnh này chỉ có thể dùng trong Server.")

        try:
            kwargs = json.loads(json_kwargs)
        except json.JSONDecodeError:
            return await ctx.send("❌ Định dạng JSON chỉnh sửa không hợp lệ.")

        await ctx.send(f"⏳ Đang cập nhật thuộc tính cho Vai trò có ID `{role_id}`...")
        result = await DiscordRole.modify_role(guild=ctx.guild, role_id=role_id, **kwargs)
        await ctx.send(f"```json\n{result}\n```")


    @commands.command(name="delete_role")
    async def delete_role_cmd(self, ctx: commands.Context, role_id: int, *, reason: str = "Được yêu cầu bởi AI Agent"):
        """
        Lệnh: !delete_role <id_vai_trò> [lý_do]
        """
        if not ctx.guild:
            return await ctx.send("❌ Lệnh này chỉ có thể dùng trong Server.")

        await ctx.send(f"⏳ Đang tiến hành xóa vai trò có ID `{role_id}`...")
        result = await DiscordRole.delete_role(guild=ctx.guild, role_id=role_id, reason=reason)
        await ctx.send(f"```json\n{result}\n```")


    @commands.command(name="assign_role")
    async def assign_role_cmd(self, ctx: commands.Context, member_id: int, role_id: int):
        """
        Lệnh: !assign_role <id_thành_viên> <id_vai_trò>
        """
        if not ctx.guild:
            return await ctx.send("❌ Lệnh này chỉ có thể dùng trong Server.")

        await ctx.send(f"⏳ Đang cấp vai trò `{role_id}` cho thành viên `{member_id}`...")
        result = await DiscordRole.assign_role_to_member(guild=ctx.guild, member_id=member_id, role_id=role_id)
        await ctx.send(f"```json\n{result}\n```")


    @commands.command(name="remove_role")
    async def remove_role_cmd(self, ctx: commands.Context, member_id: int, role_id: int):
        """
        Lệnh: !remove_role <id_thành_viên> <id_vai_trò>
        """
        if not ctx.guild:
            return await ctx.send("❌ Lệnh này chỉ có thể dùng trong Server.")

        await ctx.send(f"⏳ Đang gỡ vai trò `{role_id}` khỏi thành viên `{member_id}`...")
        result = await DiscordRole.remove_role_from_member(guild=ctx.guild, member_id=member_id, role_id=role_id)
        await ctx.send(f"```json\n{result}\n```")


    @commands.command(name="clone_role")
    async def clone_role_cmd(self, ctx: commands.Context, source_role_id: int, target_role_name: str):
        """
        Lệnh: !clone_role <id_role_gốc> <tên_role_mới>
        """
        if not ctx.guild:
            return await ctx.send("❌ Lệnh này chỉ có thể dùng trong Server.")

        await ctx.send(f"⏳ Đang sao chép nhân bản cấu hình từ Vai trò `{source_role_id}`...")
        result = await DiscordRole.clone_role(guild=ctx.guild, source_role_id=source_role_id, target_role_name=target_role_name)
        await ctx.send(f"```json\n{result}\n```")


    @commands.command(name="role_info")
    async def role_info_cmd(self, ctx: commands.Context, role_id: int):
        """
        Lệnh: !role_info <id_vai_trò>
        """
        if not ctx.guild:
            return await ctx.send("❌ Lệnh này chỉ có thể dùng trong Server.")

        await ctx.send(f"⏳ Đang phân tích ma trận quyền của vai trò `{role_id}`...")
        result = await DiscordRole.get_role_permissions_info(guild=ctx.guild, role_id=role_id)
        await ctx.send(f"```json\n{result}\n```")

# Đăng ký cog vào hệ thống bot
def setup(bot: commands.Bot):
    bot.add_cog(RoleCommand(bot))