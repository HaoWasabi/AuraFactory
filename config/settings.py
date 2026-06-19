# config/settings.py
import os
from dotenv import load_dotenv

# Tải các biến môi trường từ file .env
load_dotenv()

class Settings:
    # Khóa bảo mật API
    DISCORD_TOKEN: str = os.getenv("TOKEN_BOT", "")
    GEMINI_TOKEN: str = os.getenv("GEMINI_TOKEN", "")

    # Cấu hình hệ thống Bot
    COMMAND_PREFIX: str = "!"
    
    # Cấu hình bộ nhớ / Vector Database (Mặc định dùng ChromaDB cục bộ)
    DB_URL: str = os.getenv("DB_URL", "memory/chroma_db")
    
    # File cấu hình dữ liệu tĩnh (Bổ sung từ bot_test.py)
    VERIFY_DATA_FILE: str = "verify_data.json"

    @classmethod
    def validate(cls):
        """Kiểm tra xem các Token cốt lõi đã được điền chưa trước khi khởi động"""
        if not cls.DISCORD_TOKEN:
            raise ValueError("❌ LỖI: Thiếu TOKEN_BOT trong file .env")
        if not cls.GEMINI_TOKEN:
            raise ValueError("⚠️ CẢNH BÁO: Thiếu GEMINI_TOKEN trong file .env. Các AI Agent sẽ không thể hoạt động.")

# Chạy kiểm tra nhanh khi load module
Settings.validate()