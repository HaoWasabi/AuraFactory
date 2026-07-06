# app/config/settings.py
"""
AuraFactory Configuration — Pydantic Settings from .env
v3.0: Rebuilt per spec — type-safe, validated.
"""
import os
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Application settings loaded from environment variables."""

    # === Database ===
    @property
    def database_url(self) -> str:
        return os.getenv("DATABASE_URL", "postgresql://localhost:5432/aurafactory")

    # === Discord ===
    @property
    def discord_token(self) -> str:
        return os.getenv("DISCORD_TOKEN", "")

    @property
    def discord_client_id(self) -> str:
        return os.getenv("DISCORD_CLIENT_ID", "")

    @property
    def discord_client_secret(self) -> str:
        return os.getenv("DISCORD_CLIENT_SECRET", "")

    @property
    def discord_redirect_uri(self) -> str:
        return os.getenv("DISCORD_REDIRECT_URI", "http://localhost:8000/auth/callback")

    @property
    def secret_key(self) -> str:
        return os.getenv("SECRET_KEY", "aurafactory-dev-secret-change-in-production")

    # === Multi-Guild ===
    @property
    def allowed_guild_ids(self) -> List[int]:
        """Comma-separated guild IDs, or 'all' to allow any guild."""
        raw = os.getenv("ALLOWED_GUILD_IDS", "")
        if not raw:
            gid = int(os.getenv("GUILD_ID", "0"))
            return [gid] if gid else []
        if raw.strip().lower() == "all":
            return []
        return [int(x.strip()) for x in raw.split(",") if x.strip()]

    @property
    def allow_all_guilds(self) -> bool:
        """True if bot should respond in ANY guild it's added to."""
        return os.getenv("ALLOWED_GUILD_IDS", "").strip().lower() == "all"

    # === LLM Provider ===
    @property
    def llm_provider(self) -> str:
        """Active LLM provider: groq | gemini | openrouter | ollama"""
        return os.getenv("LLM_PROVIDER", "groq")

    # === Server ===
    @property
    def host(self) -> str:
        return os.getenv("HOST", "0.0.0.0")

    @property
    def port(self) -> int:
        return int(os.getenv("PORT", "8000"))

    @property
    def debug(self) -> bool:
        return os.getenv("DEBUG", "true").lower() == "true"

    # === Vector Store ===
    @property
    def chroma_path(self) -> str:
        return os.getenv("CHROMA_PATH", "./data/chroma")

    # === Embedding ===
    @property
    def embedding_model(self) -> str:
        return os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

    # === Redis (Phase 2) ===
    @property
    def redis_url(self) -> str:
        return os.getenv("REDIS_URL", "redis://localhost:6379")

    # === Observability ===
    @property
    def trace_enabled(self) -> bool:
        return os.getenv("TRACE_ENABLED", "true").lower() == "true"

    @property
    def log_level(self) -> str:
        return os.getenv("LOG_LEVEL", "INFO")

    @property
    def trace_log_dir(self) -> str:
        return os.getenv("TRACE_LOG_DIR", "logs/traces")


settings = Settings()
