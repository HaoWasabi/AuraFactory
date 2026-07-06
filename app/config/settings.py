"""Application settings loaded from environment variables."""

import os
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

        # LLM
        self.LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "gemini")
        self.GEMINI_TOKEN: str = os.environ.get("GEMINI_TOKEN", "")
        self.GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

        # Server
        self.PORT: int = int(os.environ.get("PORT", "8000"))
        self.SECRET_KEY: str = os.environ.get("SECRET_KEY", "change-me-in-production")
        self.DEBUG: bool = os.environ.get("DEBUG", "true").lower() in ("true", "1", "yes")

        # Database
        self.DATABASE_URL: str = os.environ.get(
            "DATABASE_URL", "postgresql://localhost:5432/aurafactory"
        )

        # AWS Bedrock flags
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

    def is_bedrock_enabled(self) -> bool:
        """Check if any Bedrock feature is enabled."""
        return self.ENABLE_BEDROCK_LLM or self.ENABLE_BEDROCK_GUARDRAILS or self.ENABLE_TITAN_EMBEDDING

    def get_llm_provider_for_agent(self, agent_name: str) -> str:
        """Return the LLM provider for a specific agent, respecting overrides.

        Falls back to the global LLM_PROVIDER if no override is configured.
        """
        import json

        try:
            overrides = json.loads(self.AGENT_LLM_OVERRIDE_ADMIN)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse AGENT_LLM_OVERRIDE_ADMIN, using default provider")
            return self.LLM_PROVIDER

        return overrides.get(agent_name, self.LLM_PROVIDER)
