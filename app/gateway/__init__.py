# app/gateway/__init__.py
"""
Layer 2 — Gateway & Control Plane.
Orchestrates all pre-processing: auth, guardrails, rate limiting,
permissions, session management, cost tracking.
"""
from app.gateway.pipeline import GatewayPipeline

__all__ = ["GatewayPipeline"]
