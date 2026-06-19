import json
import nextcord
from nextcord.ext import commands
from tools.discord_category import DiscordCategory 

class CategoryCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="create_cat")
    async def create_cat_cmd(self, ctx: commands.Context, category_name: str, *, json_kwargs: str = "{}"):
        """
        Lệnh: !create_cat "Tên Danh Mục" {"is_private": true, "allowed_role_ids": [12345]}
        """
        if not ctx.guild:
            return await ctx.send("Lệnh này chỉ có thể dùng trong Server (Guild).")

        try:
            # Parse chuỗi JSON đi kèm thành kwargs cho hàm gốc
            kwargs = json.loads(json_kwargs)
        except json.JSONDecodeError:
            return await ctx.send("❌ Định dạng cấu hình phụ (JSON) không hợp lệ.")

        await ctx.send(f"⏳ Đang thực thi tạo danh mục `{category_name}`...")
        
        # Gọi trực tiếp hàm public từ lớp DiscordCategory
        result = await DiscordCategory.create_category(ctx.guild, category_name, **kwargs)
        
        # Gửi kết quả trả về (JSON string) lên chat Discord
        await ctx.send(f"```json\n{result}\n```")


    @commands.command(name="modify_cat")
    async def modify_cat_cmd(self, ctx: commands.Context, category_id: int, *, json_kwargs: str):
        """
        Lệnh: !modify_cat 123456789 {"new_name": "Tên Mới", "position": 1}
        """
        if not ctx.guild:
            return await ctx.send("Lệnh này chỉ có thể dùng trong Server.")

        try:
            kwargs = json.loads(json_kwargs)
        except json.JSONDecodeError:
            return await ctx.send("❌ Định dạng cấu hình phụ (JSON) không hợp lệ.")

        await ctx.send(f"⏳ Đang chỉnh sửa danh mục ID `{category_id}`...")
        
        # Gọi hàm modify_category
        result = await DiscordCategory.modify_category(ctx.guild, category_id, **kwargs)
        await ctx.send(f"```json\n{result}\n```")


    @commands.command(name="sync_cat")
    async def sync_cat_cmd(self, ctx: commands.Context, category_id: int):
        """
        Lệnh: !sync_cat 123456789
        """
        if not ctx.guild:
            return await ctx.send("Lệnh này chỉ có thể dùng trong Server.")

        await ctx.send(f"⏳ Đang đồng bộ các kênh trong danh mục `{category_id}`...")
        
        # Gọi hàm sync_all_channels_in_category
        result = await DiscordCategory.sync_all_channels_in_category(ctx.guild, category_id)
        await ctx.send(f"```json\n{result}\n```")

# Hàm setup để bot load extension
def setup(bot: commands.Bot):
    bot.add_cog(CategoryCommand(bot))