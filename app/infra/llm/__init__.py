# app/infra/llm/__init__.py
"""
LLM sub-module — Provider factory + all implementations.
"""
import os
import logging
import importlib
from typing import Optional

from app.infra.llm.base import LLMProvider, LLMResponse, LLMMessage
from app.infra.llm.router import ModelRouter

logger = logging.getLogger(__name__)

# === Provider Registry ===

PROVIDER_REGISTRY = {
    "groq": {
        "module": "app.infra.llm.groq",
        "class": "GroqProvider",
        "env_key": "GROQ_API_KEY",
        "model_env": "GROQ_MODEL",
        "default_model": "llama-3.3-70b-versatile",
    },
    "gemini": {
        "module": "app.infra.llm.gemini",
        "class": "GeminiProvider",
        "env_key": "GEMINI_API_KEY",
        "model_env": "GEMINI_MODEL",
        "default_model": "gemini-2.5-flash",
    },
    "openrouter": {
        "module": "app.infra.llm.openrouter",
        "class": "OpenRouterProvider",
        "env_key": "OPENROUTER_API_KEY",
        "model_env": "OPENROUTER_MODEL",
        "default_model": "meta-llama/llama-3.1-8b-instruct:free",
    },
    "ollama": {
        "module": "app.infra.llm.ollama",
        "class": "OllamaProvider",
        "env_key": None,  # No API key needed
        "model_env": "OLLAMA_MODEL",
        "default_model": "qwen2.5:7b",
        "base_url_env": "OLLAMA_BASE_URL",
        "default_base_url": "http://localhost:11434",
    },
}


def get_provider(name: Optional[str] = None) -> LLMProvider:
    """
    Load a single LLM provider by name.
    Reads from LLM_PROVIDER env if name not given.
    Raises RuntimeError if provider is unavailable or misconfigured.
    """
    name = (name or os.getenv("LLM_PROVIDER", "groq")).lower().strip()

    if name not in PROVIDER_REGISTRY:
        raise RuntimeError(
            f"Unknown provider: '{name}'. Available: {list(PROVIDER_REGISTRY.keys())}"
        )

    config = PROVIDER_REGISTRY[name]

    # Check API key (skip for ollama)
    api_key = None
    if config.get("env_key"):
        api_key = os.getenv(config["env_key"], "")
        if not api_key:
            raise RuntimeError(
                f"Provider '{name}' requires {config['env_key']} in .env"
            )

    # Import provider class
    try:
        module = importlib.import_module(config["module"])
        provider_class = getattr(module, config["class"])
    except (ImportError, AttributeError) as e:
        raise RuntimeError(f"Cannot load provider '{name}': {e}")

    # Get model
    model_id = os.getenv(config.get("model_env", ""), config["default_model"])

    # Instantiate
    if name == "ollama":
        base_url = os.getenv(
            config.get("base_url_env", ""),
            config.get("default_base_url", "http://localhost:11434"),
        )
        return provider_class(base_url=base_url, model_id=model_id)
    else:
        return provider_class(api_key=api_key, model_id=model_id)


def list_available_providers() -> list:
    """List providers that have credentials configured."""
    available = []
    for name, config in PROVIDER_REGISTRY.items():
        if config.get("env_key") is None:
            available.append(name)  # ollama always available
        elif os.getenv(config["env_key"], ""):
            available.append(name)
    return available


__all__ = [
    "LLMProvider", "LLMResponse", "LLMMessage",
    "ModelRouter",
    "get_provider", "list_available_providers",
    "PROVIDER_REGISTRY",
]
