from fastapi import logger
import nextcord
from nextcord.ext import commands
from nextcord.message import Message
import google.generativeai as genai
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


@bot.event
async def on_message(message: Message):
    # 1. Bỏ qua tin nhắn của chính bot
    if message.author == bot.user:
        return

    if bot.user is None:
        await message.channel.send('Bot is not fully ready yet.')
        return

    # 2. Kiểm tra nếu Bot được tag (hỗ trợ cả <@ID> và <@!ID>)
    if bot.user in message.mentions:
        # Lấy prompt bằng cách xóa tag của bot đi
        prompt = message.content.replace(f'<@{bot.user.id}>', '').replace(f'<@!{bot.user.id}>', '').strip()
        
        # Nếu chỉ tag bot mà không viết gì, gợi ý người dùng
        if not prompt:
            await message.reply("Bạn cần nhập nội dung trò chuyện sau khi tag mình nhé!")
            return

        try:
            history = []

            # Lấy lịch sử 20 tin nhắn
            async for message1 in message.channel.history(limit=20):
                if message1.author.id != bot.user.id:
                    prompt1 = message1.content
                    # Làm sạch lịch sử trò chuyện (xóa tag bot nếu có)
                    prompt1 = prompt1.replace(f'<@{bot.user.id}>', '').replace(f'<@!{bot.user.id}>', '').strip()
                    if len(prompt1) > 0:
                        history.append({"role": "user", "parts": f'{message1.author.name}: "{prompt1}"'})
                else:
                    history.append({"role": "model", "parts": message1.content})

            prompt_message = await message.channel.send('Creating prompt...')

            genai.configure(api_key=os.getenv("GEMINI_TOKEN"))

            model = genai.GenerativeModel("gemini-2.5-flash")
            chat = model.start_chat(history=history[::-1])
            response = chat.send_message(f'{message.author.name}: "{prompt}"')
            response_text = response.text

            # Gửi câu trả lời chia nhỏ theo giới hạn Discord (2000 ký tự)
            chunk_size = 2000
            chunks = [response_text[i:i + chunk_size] for i in range(0, len(response_text), chunk_size)]
            
            # Xóa tin nhắn "Creating prompt..." cho sạch kênh chat
            await prompt_message.delete()
            
            response_message = await message.reply(f'@{message.author.name}, here is your response:')
            for chunk in chunks:
                await response_message.channel.send(chunk)

        except Exception as e:
            logger.error(f"Error while processing message: {e}")
            await message.channel.send('Sorry, there was an error processing your request.')
            return # Kết thúc tại đây nếu là tương tác với Gemini

    # 3. QUAN TRỌNG: Cho phép các lệnh ở trong thư mục `commands` (Cogs) hoạt động bình thường
    await bot.process_commands(message)

if __name__ == "__main__":
    # Load file wrapper lệnh test vào hệ thống bot
    # (Đảm bảo đường dẫn thư mục và file chính xác, ví dụ: cogs.test_category)
    for filename in os.listdir("commands"):
        if filename.endswith(".py") and filename != "__init__.py":
            cog_name = f"commands.{filename[:-3]}"  # Loại bỏ phần mở rộng .py
            bot.load_extension(cog_name)
            print(f"✅ Cog '{cog_name}' đã được load thành công.")
    
    bot.run(os.getenv("DISCORD_TOKEN"))