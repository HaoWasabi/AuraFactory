from .base import BaseLLM, LLMResponse, ToolCall, UsageStats
from .gemini import GeminiLLM
from .bedrock import BedrockLLM


def get_llm(provider: str = "gemini", **kwargs) -> BaseLLM:
    """Factory function to get an LLM provider instance.

    Args:
        provider: "gemini" | "bedrock"
        **kwargs: Provider-specific kwargs forwarded to the constructor.
                  Gemini: model, api_key
                  Bedrock: model, region
    """
    if provider == "gemini":
        return GeminiLLM(**kwargs)
    elif provider == "bedrock":
        return BedrockLLM(**kwargs)
    else:
        raise ValueError(
            f"Unknown LLM provider: '{provider}'. "
            f"Supported: 'gemini', 'bedrock'"
        )


def get_bedrock_llm(model: str, region: str = "us-east-1") -> BedrockLLM:
    """Convenience factory for Bedrock — used for multi-model routing."""
    return BedrockLLM(model=model, region=region)
