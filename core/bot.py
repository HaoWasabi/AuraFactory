# core/bot.py
import os
import sys
import logging
import nextcord
from nextcord.ext import commands
from dotenv import load_dotenv

# Fix path mạnh hơn
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

load_dotenv()

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

intents = nextcord.Intents.all()
intents.message_content = True
intents.members = True

class AgenticDiscordBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
            case_insensitive=True,
            help_command=commands.DefaultHelpCommand()
        )

    async def on_ready(self):
        logger.info(f"✅ Bot online | {self.user}")
        activity = nextcord.Activity(type=nextcord.ActivityType.watching, name="!help | AuraFactory")
        await self.change_presence(status=nextcord.Status.online, activity=activity)


bot = AgenticDiscordBot()

# ====================== THÊM COG TRỰC TIẾP ======================
@bot.event
async def setup_hook():
    try:
        print("🔄 Đang import TestToolsCog...")
        from tests.test_tools import TestToolsCog
        print("✅ Import thành công, đang add cog...")
        
        await bot.add_cog(TestToolsCog(bot))
        
        logger.info("✅ TestToolsCog ĐÃ LOAD THÀNH CÔNG!")
        print("🎉=== TESTTOOLSCOG LOADED SUCCESSFULLY ===")
        
    except Exception as e:
        logger.error(f"❌ LỖI KHI LOAD COG: {type(e).__name__} - {e}")
        print(f"❌ LỖI LOAD COG: {type(e).__name__} - {e}")


@bot.command()
async def ping(ctx):
    await ctx.send(f"🏓 Pong! `{round(bot.latency * 1000)}ms`")


@bot.command(name="reload_test")
@commands.has_permissions(administrator=True)
async def reload_test(ctx):
    try:
        if "TestToolsCog" in bot.cogs:
            bot.remove_cog("TestToolsCog")
        from tests.test_tools import TestToolsCog
        await bot.add_cog(TestToolsCog(bot))
        await ctx.send("✅ Reload thành công! Gõ `!help` kiểm tra.")
    except Exception as e:
        await ctx.send(f"❌ Reload lỗi: {e}")


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ Không tìm thấy DISCORD_TOKEN trong .env")
        sys.exit(1)
    logger.info("🚀 Khởi động bot...")
    bot.run(token)