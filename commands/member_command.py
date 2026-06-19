import json
import nextcord
from nextcord.ext import commands
from tools.discord_member import DiscordMember 

class MemberCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="kick")
    async def kick_cmd(self, ctx: commands.Context, member_id: int, *, reason: str = "Được yêu cầu bởi AI Agent"):
        """
        Lệnh: !kick <id_thành_viên> [lý_do]
        """
        if not ctx.guild:
            return await ctx.send("❌ Lệnh này chỉ có thể dùng trong Server.")

        await ctx.send(f"⏳ Đang xử lý trục xuất thành viên `{member_id}`...")
        
        result = await DiscordMember.kick_member(guild=ctx.guild, member_id=member_id, reason=reason)
        await ctx.send(f"```json\n{result}\n```")


    @commands.command(name="ban")
    async def ban_cmd(self, ctx: commands.Context, member_id: int, delete_seconds: int = 0, *, reason: str = "Được yêu cầu bởi AI Agent"):
        """
        Lệnh: !ban <id_thành_viên> [giây_xóa_tin_nhắn] [lý_do]
        """
        if not ctx.guild:
            return await ctx.send("❌ Lệnh này chỉ có thể dùng trong Server.")

        await ctx.send(f"⏳ Đang xử lý cấm thành viên `{member_id}` khỏi server...")
        
        result = await DiscordMember.ban_member(
            guild=ctx.guild, 
            member_id=member_id, 
            delete_message_seconds=delete_seconds, 
            reason=reason
        )
        await ctx.send(f"```json\n{result}\n```")


    @commands.command(name="unban")
    async def unban_cmd(self, ctx: commands.Context, member_id: int, *, reason: str = "Được yêu cầu bởi AI Agent"):
        """
        Lệnh: !unban <id_thành_viên> [lý_do]
        """
        if not ctx.guild:
            return await ctx.send("❌ Lệnh này chỉ có thể dùng trong Server.")

        await ctx.send(f"⏳ Đang xử lý gỡ cấm cho ID `{member_id}`...")
        
        result = await DiscordMember.unban_member(guild=ctx.guild, member_id=member_id, reason=reason)
        await ctx.send(f"```json\n{result}\n```")


    @commands.command(name="timeout")
    async def timeout_cmd(self, ctx: commands.Context, member_id: int, duration_minutes: int, *, reason: str = "Được yêu cầu bởi AI Agent"):
        """
        Lệnh: !timeout <id_thành_viên> <số_phút> [lý_do] (Đặt phút = 0 để gỡ timeout)
        """
        if not ctx.guild:
            return await ctx.send("❌ Lệnh này chỉ có thể dùng trong Server.")

        if duration_minutes > 0:
            await ctx.send(f"⏳ Đang xử lý cấm túc thành viên `{member_id}` trong {duration_minutes} phút...")
        else:
            await ctx.send(f"⏳ Đang gỡ cấm túc cho thành viên `{member_id}`...")
            
        result = await DiscordMember.timeout_member(
            guild=ctx.guild, 
            member_id=member_id, 
            duration_minutes=duration_minutes, 
            reason=reason
        )
        await ctx.send(f"```json\n{result}\n```")


    @commands.command(name="purge")
    async def purge_cmd(self, ctx: commands.Context, channel_id: int, limit: int = 100, *, json_kwargs: str = "{}"):
        """
        Lệnh thông thường: !purge <id_kênh> <số_lượng_tin>
        Lệnh lọc theo người dùng: !purge <id_kênh> <số_lượng_tin> {"member_id": 123456789}
        """
        if not ctx.guild:
            return await ctx.send("❌ Lệnh này chỉ có thể dùng trong Server.")

        try:
            kwargs = json.loads(json_kwargs)
        except json.JSONDecodeError:
            return await ctx.send("❌ Chuỗi JSON bổ sung để lọc người dùng bị sai định dạng.")

        await ctx.send(f"⏳ Đang tiến hành quét và dọn dẹp tin nhắn tại kênh `{channel_id}`...")
        
        result = await DiscordMember.purge_messages(
            guild=ctx.guild, 
            channel_id=channel_id, 
            limit=limit, 
            **kwargs
        )
        await ctx.send(f"```json\n{result}\n```")


    @commands.command(name="setnick")
    async def setnick_cmd(self, ctx: commands.Context, member_id: int, *, nickname: str = ""):
        """
        Lệnh đổi tên: !setnick <id_thành_viên> <biệt_danh_mới>
        Lệnh reset tên gốc: !setnick <id_thành_viên>
        """
        if not ctx.guild:
            return await ctx.send("❌ Lệnh này chỉ có thể dùng trong Server.")

        # Nếu truyền chuỗi trống hoặc chỉ gõ khoảng cách, ép về None để xóa nick theo thiết kế hàm gốc
        new_nick = nickname.strip() if nickname.strip() else None
        
        await ctx.send(f"⏳ Đang xử lý thay đổi biệt danh cho thành viên `{member_id}`...")
        
        result = await DiscordMember.modify_member_nickname(
            guild=ctx.guild, 
            member_id=member_id, 
            new_nickname=new_nick, 
            reason="Lệnh test từ Admin"
        )
        await ctx.send(f"```json\n{result}\n```")

# Đăng ký cog vào bot
def setup(bot: commands.Bot):
    bot.add_cog(MemberCommand(bot))