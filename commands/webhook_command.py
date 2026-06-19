import json
import nextcord
from nextcord.ext import commands
from tools.discord_webhook import DiscordWebhook 

class WebhookCommand(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="create_webhook")
    async def create_webhook_cmd(self, ctx: commands.Context, channel_id: int, webhook_name: str, avatar_url: str = None):
        """
        Lệnh: !create_webhook <id_kênh> <tên_webhook> [url_ảnh_đại_diện]
        """
        if not ctx.guild:
            return await ctx.send("❌ Lệnh này chỉ có thể dùng trong Server.")

        await ctx.send(f"⏳ Đang khởi tạo Webhook `{webhook_name}` tại kênh `{channel_id}`...")
        result = await DiscordWebhook.create_webhook(
            guild=ctx.guild, 
            channel_id=channel_id, 
            webhook_name=webhook_name, 
            avatar_url=avatar_url
        )
        await ctx.send(f"```json\n{result}\n```")


    @commands.command(name="execute_webhook")
    async def execute_webhook_cmd(self, ctx: commands.Context, webhook_url: str, *, content_or_json: str):
        """
        Lệnh gửi chữ thuần: !execute_webhook <url_webhook> Hello World!
        Lệnh gửi Embed cấu trúc nâng cao: !execute_webhook <url_webhook> {"embeds": [{"title": "Test", "description": "Nội dung"}]}
        """
        await ctx.send("⏳ Đang tiến hành bắn payload qua Webhook URL...")
        
        # Thử phân tích xem người dùng đang truyền chuỗi chữ thông thường hay JSON nâng cao
        try:
            payload = json.loads(content_or_json)
            content = payload.get("content", None)
            embeds = payload.get("embeds", None)
            username = payload.get("username", None)
            avatar_url = payload.get("avatar_url", None)
        except json.JSONDecodeError:
            # Nếu không phải JSON, mặc định hiểu đây là tin nhắn chữ (content) thuần túy
            content = content_or_json
            embeds = None
            username = None
            avatar_url = None

        result = await DiscordWebhook.execute_webhook_raw(
            webhook_url=webhook_url,
            content=content,
            embeds=embeds,
            username=username,
            avatar_url=avatar_url
        )
        await ctx.send(f"```json\n{result}\n```")


    @commands.command(name="test_github_transform")
    async def test_github_transform_cmd(self, ctx: commands.Context, webhook_url: str, event_type: str, *, mock_payload_json: str):
        """
        Giả lập payload GitHub gửi đến, chuyển đổi thành Embed rồi bắn thẳng vào webhook_url để check giao diện.
        Lệnh: !test_github_transform <url_webhook> <push/issues> <chuỗi_json_giả_lập>
        """
        try:
            payload_dict = json.loads(mock_payload_json)
        except json.JSONDecodeError:
            return await ctx.send("❌ Chuỗi JSON mock payload của GitHub bị sai định dạng.")

        await ctx.send(f"⚙️ Đang dịch chuyển đổi (Transform) payload GitHub event `{event_type}`...")
        
        # Gọi bộ Transformer dịch mảng dữ liệu thô sang Embed mẫu của Discord
        transformed_data = DiscordWebhook.transform_github_payload(event_type=event_type, payload_dict=payload_dict)
        
        # Bắn kết quả sau khi dịch vào kênh thông qua phương thức gửi raw
        await ctx.send("🚀 Đang gửi Embed kết quả qua Webhook...")
        result = await DiscordWebhook.execute_webhook_raw(
            webhook_url=webhook_url,
            embeds=transformed_data.get("embeds"),
            username="GitHub Sandbox"
        )
        await ctx.send(f"```json\n{result}\n```")


    @commands.command(name="test_gitlab_transform")
    async def test_gitlab_transform_cmd(self, ctx: commands.Context, webhook_url: str, object_kind: str, *, mock_payload_json: str):
        """
        Giả lập payload GitLab gửi đến, chuyển đổi thành Embed rồi bắn vào webhook_url.
        Lệnh: !test_gitlab_transform <url_webhook> <push/merge_request> <chuỗi_json_giả_lập>
        """
        try:
            payload_dict = json.loads(mock_payload_json)
        except json.JSONDecodeError:
            return await ctx.send("❌ Chuỗi JSON mock payload của GitLab bị sai định dạng.")

        await ctx.send(f"⚙️ Đang dịch chuyển đổi (Transform) payload GitLab object `{object_kind}`...")
        
        transformed_data = DiscordWebhook.transform_gitlab_payload(object_kind=object_kind, payload_dict=payload_dict)
        
        await ctx.send("🚀 Đang gửi Embed kết quả qua Webhook...")
        result = await DiscordWebhook.execute_webhook_raw(
            webhook_url=webhook_url,
            embeds=transformed_data.get("embeds"),
            username="GitLab Sandbox"
        )
        await ctx.send(f"```json\n{result}\n```")

# Đăng ký cog vào hệ thống bot
def setup(bot: commands.Bot):
    bot.add_cog(WebhookCommand(bot))