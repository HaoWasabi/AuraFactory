"""Application settings loaded from environment variables."""

import os
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class Settings:
    """Central application settings sourced from environment variables."""

    def __init__(self) -> None:
        # Discord
        self.DISCORD_TOKEN: str = os.environ.get("DISCORD_TOKEN", "")
        self.GUILD_ID: str = os.environ.get("GUILD_ID", "")
        self.DISCORD_CLIENT_ID: str = os.environ.get("DISCORD_CLIENT_ID", "")
        self.DISCORD_CLIENT_SECRET: str = os.environ.get("DISCORD_CLIENT_SECRET", "")
        self.DISCORD_REDIRECT_URI: str = os.environ.get("DISCORD_REDIRECT_URI", "")
        self.ALLOWED_GUILD_IDS: str = os.environ.get("ALLOWED_GUILD_IDS", "")

        # LLM
        self.LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "gemini")
        self.GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", os.environ.get("GEMINI_TOKEN", ""))
        self.GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        self.GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")
        self.OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY", "")
        self.OPENROUTER_MODEL: str = os.environ.get("OPENROUTER_MODEL", "google/gemini-flash-1.5")
        self.OLLAMA_BASE_URL: str = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        self.OLLAMA_MODEL: str = os.environ.get("OLLAMA_MODEL", "llama3")

        # Server
        self.PORT: int = int(os.environ.get("PORT", "8000"))
        self.SECRET_KEY: str = os.environ.get("SECRET_KEY", "change-me-in-production")
        self.DEBUG: bool = os.environ.get("DEBUG", "true").lower() in ("true", "1", "yes")
        self.LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")

        # Database
        self.DATABASE_URL: str = os.environ.get(
            "DATABASE_URL", "postgresql://localhost:5432/aurafactory"
        )

        # Paths
        self.TRACE_LOG_DIR: str = os.environ.get("TRACE_LOG_DIR", "logs/traces")
        self.SKILLS_DIR: str = os.environ.get("SKILLS_DIR", "skills")
        self.PROMPTS_DIR: str = os.environ.get("PROMPTS_DIR", "prompts")

        # AWS Bedrock flags (Phase 2)
        self.ENABLE_BEDROCK_LLM: bool = os.environ.get("ENABLE_BEDROCK_LLM", "false").lower() in ("true", "1", "yes")
        self.ENABLE_BEDROCK_GUARDRAILS: bool = os.environ.get("ENABLE_BEDROCK_GUARDRAILS", "false").lower() in ("true", "1", "yes")
        self.ENABLE_TITAN_EMBEDDING: bool = os.environ.get("ENABLE_TITAN_EMBEDDING", "false").lower() in ("true", "1", "yes")

        # AWS credentials
        self.AWS_REGION: str = os.environ.get("AWS_REGION", "us-east-1")
        self.AWS_ACCESS_KEY_ID: str = os.environ.get("AWS_ACCESS_KEY_ID", "")
        self.AWS_SECRET_ACCESS_KEY: str = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
        self.BEDROCK_MODEL_ID: str = os.environ.get("BEDROCK_MODEL_ID", "")

        # Agent LLM override mapping (JSON string: {"agent_name": "provider_name"})
        self.AGENT_LLM_OVERRIDE_ADMIN: str = os.environ.get("AGENT_LLM_OVERRIDE_ADMIN", "{}")

        logger.info("Settings loaded (provider=%s, debug=%s)", self.LLM_PROVIDER, self.DEBUG)

    # ================================================================
    # Lowercase property aliases (used by main.py and other modules)
    # ================================================================

    @property
    def discord_token(self) -> str:
        return self.DISCORD_TOKEN

    @property
    def discord_client_id(self) -> str:
        return self.DISCORD_CLIENT_ID

    @property
    def discord_client_secret(self) -> str:
        return self.DISCORD_CLIENT_SECRET

    @property
    def discord_redirect_uri(self) -> str:
        return self.DISCORD_REDIRECT_URI

    @property
    def allowed_guild_ids(self) -> list:
        if not self.ALLOWED_GUILD_IDS:
            return []
        return [gid.strip() for gid in self.ALLOWED_GUILD_IDS.split(",") if gid.strip()]

    @property
    def llm_provider(self) -> str:
        return self.LLM_PROVIDER

    @property
    def gemini_api_key(self) -> str:
        return self.GEMINI_API_KEY

    @property
    def gemini_model(self) -> str:
        return self.GEMINI_MODEL

    @property
    def groq_api_key(self) -> str:
        return self.GROQ_API_KEY

    @property
    def openrouter_api_key(self) -> str:
        return self.OPENROUTER_API_KEY

    @property
    def openrouter_model(self) -> str:
        return self.OPENROUTER_MODEL

    @property
    def ollama_base_url(self) -> str:
        return self.OLLAMA_BASE_URL

    @property
    def ollama_model(self) -> str:
        return self.OLLAMA_MODEL

    @property
    def port(self) -> int:
        return self.PORT

    @property
    def secret_key(self) -> str:
        return self.SECRET_KEY

    @property
    def debug(self) -> bool:
        return self.DEBUG

    @property
    def log_level(self) -> str:
        return self.LOG_LEVEL

    @property
    def database_url(self) -> str:
        return self.DATABASE_URL

    @property
    def trace_log_dir(self) -> str:
        return self.TRACE_LOG_DIR

    @property
    def skills_dir(self) -> str:
        return self.SKILLS_DIR

    @property
    def prompts_dir(self) -> str:
        return self.PROMPTS_DIR

    # ================================================================
    # Utility methods
    # ================================================================

    def is_bedrock_enabled(self) -> bool:
        """Check if any Bedrock feature is enabled."""
        return self.ENABLE_BEDROCK_LLM or self.ENABLE_BEDROCK_GUARDRAILS or self.ENABLE_TITAN_EMBEDDING

    def get_llm_provider_for_agent(self, agent_name: str) -> str:
        """Return the LLM provider for a specific agent, respecting overrides."""
        try:
            overrides = json.loads(self.AGENT_LLM_OVERRIDE_ADMIN)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse AGENT_LLM_OVERRIDE_ADMIN, using default provider")
            return self.LLM_PROVIDER

        return overrides.get(agent_name, self.LLM_PROVIDER)


# ================================================================
# Singleton instance — import this everywhere
# ================================================================
settings = Settings()
