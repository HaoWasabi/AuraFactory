from .base import BaseLLM, LLMResponse, ToolCall, UsageStats
from .gemini import GeminiLLM

def get_llm(provider: str = "gemini", **kwargs) -> BaseLLM:
    """Factory function to get an LLM provider instance."""
    if provider == "gemini":
        return GeminiLLM(**kwargs)
    elif provider == "bedrock":
        from .bedrock import BedrockLLM
        return BedrockLLM(**kwargs)
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
