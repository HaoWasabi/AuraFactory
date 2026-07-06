"""Observability infrastructure - tracing and metrics."""
from .tracer import Tracer
from .metrics import Metrics

# Singleton instance for convenience (main.py imports lowercase `metrics`)
metrics = Metrics()

__all__ = ["Tracer", "Metrics", "metrics"]
