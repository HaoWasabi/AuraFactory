"""LLM provider infrastructure."""
import logging
from app.config.settings import settings
from .router import LLMRouter
from .base import BaseLLM, LLMResponse, ToolCall, UsageStats

logger = logging.getLogger(__name__)

# Alias
LLMProvider = BaseLLM


def get_provider(provider_name: str = None) -> BaseLLM:
    """Factory function to create an LLM provider from settings."""
    provider_name = provider_name or settings.llm_provider
    router = LLMRouter()

    if provider_name == "gemini":
        return router.create_provider("gemini", model=settings.gemini_model, api_key=settings.gemini_api_key)
    elif provider_name == "groq":
        return router.create_provider("groq", model="llama-3.1-70b-versatile", api_key=settings.groq_api_key)
    elif provider_name == "openrouter":
        return router.create_provider("openrouter", model=settings.openrouter_model, api_key=settings.openrouter_api_key)
    elif provider_name == "ollama":
        return router.create_provider("ollama", model=settings.ollama_model, api_key="")
    else:
        logger.warning(f"Unknown provider '{provider_name}', falling back to gemini")
        return router.create_provider("gemini", model=settings.gemini_model, api_key=settings.gemini_api_key)


class ModelRouter:
    """Simple model router that wraps a primary provider."""

    def __init__(self, primary: BaseLLM):
        self.primary = primary

    async def generate(self, prompt: str, tools=None, temperature=0.7):
        return await self.primary.generate(prompt, tools=tools, temperature=temperature)


__all__ = ["LLMRouter", "ModelRouter", "get_provider", "BaseLLM", "LLMProvider", "LLMResponse", "ToolCall", "UsageStats"]
