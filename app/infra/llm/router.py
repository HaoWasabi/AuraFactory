# app/infra/llm/router.py
"""
Model Router — selects optimal model configuration per task type.
Phase 1: Single provider, just adjust temperature/tokens.
Phase 2: Can route to different providers per task.
"""
from typing import Dict, Any


class ModelRouter:
    """
    Select model configuration per task type.
    Planning tasks → higher temperature, more tokens.
    Classification → low temperature, fewer tokens.
    """

    DEFAULT_ROUTING_TABLE: Dict[str, Dict[str, Any]] = {
        "planning": {"temperature": 0.4, "max_tokens": 3000},
        "reasoning": {"temperature": 0.3, "max_tokens": 2000},
        "synthesis": {"temperature": 0.5, "max_tokens": 1500},
        "classification": {"temperature": 0.1, "max_tokens": 500},
        "tool_calling": {"temperature": 0.2, "max_tokens": 2000},
        "conversation": {"temperature": 0.7, "max_tokens": 1000},
    }

    def __init__(self, routing_table: Dict[str, Dict[str, Any]] | None = None):
        self._table = routing_table or self.DEFAULT_ROUTING_TABLE

    def get_config(self, task_type: str) -> Dict[str, Any]:
        """Get model configuration for a task type."""
        return self._table.get(task_type, self._table["reasoning"])

    def register_task_type(self, task_type: str, config: Dict[str, Any]) -> None:
        """Register or override a task type configuration."""
        self._table[task_type] = config
