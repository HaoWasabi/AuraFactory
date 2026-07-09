"""Core modules for AuraFactory UnifiedAgent v2.

Three resilience patterns:
  1. LLMResponseNormalizer — guaranteed output shape from any LLM
  2. RequestStore + RequestLifecycle — stateful FSM per request
  3. ExecutionPipeline + Middleware — composable execution chain

Supporting modules:
  - SpecRegistry — tools_spec.yaml loader
  - ToolGraph — NetworkX dependency graph + top-k retrieval
  - KwargsFilter — runtime kwarg validation
  - Safety layers — ApprovalGate, GuildLock, AuditLogger, ConversationMemory
"""

from app.core.spec_loader import SpecRegistry, ToolSpec
from app.core.tool_graph import ToolGraph
from app.core.kwargs_filter import KwargsFilter
from app.core.normalizer import LLMResponseNormalizer, NormalizedLLMOutput, NormalizedToolCall
from app.core.request_lifecycle import RequestStore, RequestLifecycle, RequestState
from app.core.middleware import (
    ExecutionPipeline, ExecutionContext, ExecutionResult,
    Middleware, ErrorBoundaryMiddleware, RateLimitMiddleware,
    RetryMiddleware, AuditMiddleware, MemoryMiddleware,
)
from app.core.safety import (
    ApprovalGate, RateLimiter, GuildLock,
    AuditLogger, RetryPolicy, ConversationMemory,
)

__all__ = [
    # Spec
    "SpecRegistry", "ToolSpec", "ToolGraph", "KwargsFilter",
    # Pattern 1: Normalizer
    "LLMResponseNormalizer", "NormalizedLLMOutput", "NormalizedToolCall",
    # Pattern 2: Request Lifecycle
    "RequestStore", "RequestLifecycle", "RequestState",
    # Pattern 3: Middleware Pipeline
    "ExecutionPipeline", "ExecutionContext", "ExecutionResult",
    "Middleware", "ErrorBoundaryMiddleware", "RateLimitMiddleware",
    "RetryMiddleware", "AuditMiddleware", "MemoryMiddleware",
    # Safety
    "ApprovalGate", "RateLimiter", "GuildLock",
    "AuditLogger", "RetryPolicy", "ConversationMemory",
]
