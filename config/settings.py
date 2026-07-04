# config/settings.py
"""
Well-Architected (Cost): Adopt a consumption model
Centralized config — đổi provider/model ở 1 chỗ duy nhất.
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # === Discord ===
    DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", os.getenv("TOKEN_BOT", ""))
    COMMAND_PREFIX: str = "!"
    
    # === LLM Provider ===
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini")  # "gemini" | "bedrock"
    
    # Gemini (Phase 1)
    GEMINI_TOKEN: str = os.getenv("GEMINI_TOKEN", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    
    # Bedrock (Phase 2 — uncomment khi ready)
    AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")
    BEDROCK_MODEL_ID: str = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
    
    # === Observability ===
    LOG_TRACES: bool = os.getenv("LOG_TRACES", "true").lower() == "true"
    LOG_DIR: str = os.getenv("LOG_DIR", "logs/traces")
    
    # === Knowledge Base ===
    KB_PROVIDER: str = os.getenv("KB_PROVIDER", "local")  # "local" | "bedrock"
    
    # === Legacy (backward compat với main.py cũ) ===
    DB_URL: str = os.getenv("DB_URL", "memory/chroma_db")
    VERIFY_DATA_FILE: str = "verify_data.json"

    @classmethod
    def validate(cls):
        """Kiểm tra tokens cần thiết trước khi khởi động"""
        if not cls.DISCORD_TOKEN:
            raise ValueError("❌ Thiếu DISCORD_TOKEN trong .env")
        
        if cls.LLM_PROVIDER == "gemini" and not cls.GEMINI_TOKEN:
            raise ValueError("⚠️ LLM_PROVIDER=gemini nhưng thiếu GEMINI_TOKEN")
        
        if cls.LLM_PROVIDER == "bedrock":
            # Phase 2: check boto3 available
            try:
                import boto3
            except ImportError:
                raise ValueError("❌ LLM_PROVIDER=bedrock nhưng chưa install boto3. Run: pip install boto3")
    
    @classmethod
    def get_llm_config(cls) -> dict:
        """Trả về config cho LLM provider hiện tại"""
        if cls.LLM_PROVIDER == "gemini":
            return {
                "provider": "gemini",
                "api_key": cls.GEMINI_TOKEN,
                "model_id": cls.GEMINI_MODEL,
            }
        elif cls.LLM_PROVIDER == "bedrock":
            return {
                "provider": "bedrock",
                "region": cls.AWS_REGION,
                "model_id": cls.BEDROCK_MODEL_ID,
            }
        else:
            raise ValueError(f"Unknown LLM_PROVIDER: {cls.LLM_PROVIDER}")


# Validate khi import
Settings.validate()
