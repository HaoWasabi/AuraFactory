import nextcord
from nextcord.ext import commands
import os
from dotenv import load_dotenv

load_dotenv()

# Cấu hình Intents
intents = nextcord.Intents.default()
intents.message_content = True  # Bắt buộc bật để bot đọc được lệnh prefix "!"
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"🤖 Bot test đã sẵn sàng: {bot.user.name}")

if __name__ == "__main__":
    # Load file wrapper lệnh test vào hệ thống bot
    # (Đảm bảo đường dẫn thư mục và file chính xác, ví dụ: cogs.test_category)
    for filename in os.listdir("commands"):
        if filename.endswith(".py") and filename != "__init__.py":
            cog_name = f"commands.{filename[:-3]}"  # Loại bỏ phần mở rộng .py
            bot.load_extension(cog_name)
            print(f"✅ Cog '{cog_name}' đã được load thành công.")
    
    bot.run(os.getenv("DISCORD_TOKEN"))