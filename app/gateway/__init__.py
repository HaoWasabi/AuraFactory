# app/gateway/__init__.py
"""
Layer 2 — Gateway & Control Plane.
Orchestrates all pre-processing: rate limiting, guardrails, role detection,
session management, cost tracking.

Pipeline order: rate_limit → guardrails → role_detection → session_resolve → cost_check
"""
from app.gateway.pipeline import GatewayPipeline

__all__ = ["GatewayPipeline"]
