"""LLM Router - factory and agent-level provider resolution."""

import logging
from typing import Optional

from .base import BaseLLM
from .gemini import GeminiLLM
from .groq import GroqLLM
from .openrouter import OpenRouterLLM
from .ollama import OllamaLLM

logger = logging.getLogger(__name__)

PROVIDER_MAP = {
    "gemini": GeminiLLM,
    "groq": GroqLLM,
    "openrouter": OpenRouterLLM,
    "ollama": OllamaLLM,
}


class LLMRouter:
    """Routes LLM requests to the appropriate provider."""

    def __init__(self) -> None:
        self._providers: dict[str, BaseLLM] = {}

    def create_provider(self, provider_name: str, model: str = "", api_key: str = "") -> BaseLLM:
        """Create and cache a provider instance by name.

        Args:
            provider_name: One of gemini, groq, openrouter, ollama, bedrock.
            model: Model identifier (provider-specific).
            api_key: API key for the provider.

        Returns:
            An instance of BaseLLM.

        Raises:
            ValueError: If the provider name is not recognized or not available.
        """
        if provider_name == "bedrock":
            raise ValueError(
                "Bedrock provider is not available in Phase 1. "
                "Set ENABLE_BEDROCK_LLM=true and implement the Bedrock provider."
            )

        provider_class = PROVIDER_MAP.get(provider_name)
        if provider_class is None:
            raise ValueError(
                f"Unknown LLM provider: '{provider_name}'. "
                f"Available: {list(PROVIDER_MAP.keys())}"
            )

        cache_key = f"{provider_name}:{model}"
        if cache_key not in self._providers:
            instance = provider_class(model=model, api_key=api_key)
            self._providers[cache_key] = instance
            logger.info("Created LLM provider: %s (model=%s)", provider_name, model)

        return self._providers[cache_key]

    def get_provider_for_agent(self, agent_name: str, settings: "Any") -> BaseLLM:
        """Resolve the LLM provider for a specific agent.

        Checks agent-level overrides first, then falls back to default.

        Args:
            agent_name: The name of the agent requesting an LLM.
            settings: Application Settings instance.

        Returns:
            A BaseLLM provider instance.
        """
        provider_name = settings.get_llm_provider_for_agent(agent_name)

        # Determine model and API key based on provider
        if provider_name == "gemini":
            model = settings.GEMINI_MODEL
            api_key = settings.GEMINI_TOKEN
        elif provider_name == "groq":
            model = getattr(settings, "GROQ_MODEL", "llama-3.1-70b-versatile")
            api_key = getattr(settings, "GROQ_API_KEY", "")
        elif provider_name == "openrouter":
            model = getattr(settings, "OPENROUTER_MODEL", "openai/gpt-4o")
            api_key = getattr(settings, "OPENROUTER_API_KEY", "")
        elif provider_name == "ollama":
            model = getattr(settings, "OLLAMA_MODEL", "llama3.1")
            api_key = ""
        else:
            model = settings.GEMINI_MODEL
            api_key = settings.GEMINI_TOKEN
            provider_name = "gemini"

        logger.debug("Agent '%s' using provider '%s' (model=%s)", agent_name, provider_name, model)
        return self.create_provider(provider_name, model=model, api_key=api_key)
