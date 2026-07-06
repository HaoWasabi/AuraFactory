# app/agents/fast_track.py
"""
Fast Track — single LLM call to extract actions, then batch execute.
For simple commands: "tạo channel X", "kick user Y", "xóa role Z".
No reasoning loop. No multi-turn. Just extract → validate → execute → respond.
"""
import json
import logging
from typing import Dict, Any, List

from app.infra.llm.base import LLMProvider
from app.infra.observability.tracer import Tracer
from app.infra.observability.metrics import metrics
from app.mcp import MCPClient
from app.gateway.pipeline import GatewayContext

logger = logging.getLogger(__name__)

EXTRACT_PROMPT = """You are AuraFactory — extract Discord actions from user request.

Return JSON array of actions. Each action: {{"tool": "tool_name", "params": {{...}}}}
guild_id is auto-injected, don't include it.

Available tools:
- create_channel: params: name*, channel_type (text|voice|forum), category, topic
- create_category: params: name*
- create_role: params: name*, color, mentionable, hoist
- assign_role: params: user_id*, role_name*
- edit_channel: params: channel_name*, new_name, new_topic, slowmode
- delete_channel: params: channel_name*
- delete_role: params: role_name*
- kick_member: params: user_id*, reason
- ban_member: params: user_id*, reason
- set_channel_permission: params: channel_name*, target_name*, allow, deny

(* = required)

User request: "{message}"

Server context: {server_context}

Return JSON array only. If unsure, return [].
"""

RESPONSE_TEMPLATE_VI = """✅ Đã thực hiện {success}/{total} thao tác:
{results}"""

RESPONSE_TEMPLATE_EN = """✅ Completed {success}/{total} actions:
{results}"""


class FastTrackExecutor:
    """
    Simple command handler — no loop, no reasoning.
    1 LLM call → extract actions → batch validate+execute → respond.
    """

    def __init__(
        self,
        llm: LLMProvider,
        tracer: Tracer,
        mcp_client: MCPClient,
    ):
        self._llm = llm
        self._tracer = tracer
        self._mcp = mcp_client
        self._skill_validator = None
        self._skill_registry = None

    def set_skill_registry(self, registry, validator=None) -> None:
        self._skill_registry = registry
        self._skill_validator = validator

    async def handle(
        self,
        prompt: str,
        guild_id: int,
        server_context: str,
        context: GatewayContext = None,
    ) -> Dict[str, Any]:
        """
        Fast track: extract → validate → execute → respond.
        Total: 1 LLM call only.
        """
        trace_id = context.trace_id if context else "no-trace"
        logger.info(f"[{trace_id}] FastTrack handling: {prompt[:50]}...")

        # ─── Step 1: Extract actions (1 LLM call) ───
        actions = await self._extract_actions(prompt, server_context)

        if not actions:
            return {
                "status": "response",
                "content": "Xin lỗi, tôi không hiểu yêu cầu. Bạn có thể nói rõ hơn?",
                "trace_id": trace_id,
                "mode": "fast_track",
            }

        # ─── Step 2: Check risk — any HIGH+ → reject with explanation ───
        high_risk = []
        if self._skill_registry:
            for action in actions:
                risk = self._skill_registry.get_risk_level(action.get("tool", ""))
                if risk in ("high", "critical"):
                    high_risk.append(action["tool"])

        if high_risk:
            tools_str = ", ".join(high_risk)
            return {
                "status": "confirm",
                "content": f"⚠️ Thao tác nguy hiểm: **{tools_str}**. Không thể hoàn tác. Bạn xác nhận?",
                "trace_id": trace_id,
                "mode": "fast_track",
            }

        # ─── Step 3: Validate + Execute batch ───
        results = []
        for action in actions:
            tool_name = action.get("tool", "")
            params = action.get("params", {})

            # Auto-inject guild_id
            params["guild_id"] = guild_id

            # Coerce string guild_id
            if isinstance(params.get("guild_id"), str):
                try:
                    params["guild_id"] = int(params["guild_id"])
                except ValueError:
                    pass

            # Validate
            if self._skill_validator:
                vr = self._skill_validator.validate(tool_name, params)
                if not vr.is_valid:
                    results.append({"tool": tool_name, "ok": False, "error": vr.error_message})
                    continue
                params = vr.sanitized_params

            # Execute
            try:
                resp = await self._mcp.call_tool(tool_name, params)
                if hasattr(resp, "success") and not resp.success:
                    results.append({"tool": tool_name, "ok": False, "error": resp.error or "Failed"})
                else:
                    results.append({"tool": tool_name, "ok": True})
            except Exception as e:
                results.append({"tool": tool_name, "ok": False, "error": str(e)})

        # ─── Step 4: Format response ───
        success_count = sum(1 for r in results if r["ok"])
        total = len(results)

        result_lines = []
        for r in results:
            if r["ok"]:
                result_lines.append(f"  ✅ {r['tool']}")
            else:
                result_lines.append(f"  ❌ {r['tool']}: {r.get('error', 'failed')}")

        content = RESPONSE_TEMPLATE_VI.format(
            success=success_count,
            total=total,
            results="\n".join(result_lines),
        )

        metrics.increment("fast_track_executed", labels={"success": str(success_count == total)})

        return {
            "status": "response",
            "content": content,
            "trace_id": trace_id,
            "mode": "fast_track",
            "actions_executed": total,
        }

    async def _extract_actions(self, prompt: str, server_context: str) -> List[Dict]:
        """Single LLM call to extract structured actions."""
        system = EXTRACT_PROMPT.format(
            message=prompt[:500],
            server_context=server_context[:300],
        )

        try:
            response = await self._llm.generate(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=system,
                temperature=0.0,
                max_tokens=500,
            )

            raw = response.content.strip()
            metrics.count_request(response.model, "fast_track_extract", "success")
            metrics.count_tokens(response.model, response.input_tokens, response.output_tokens)

            # Parse JSON array
            return self._parse_actions(raw)

        except Exception as e:
            logger.error(f"FastTrack extract error: {e}")
            return []

    def _parse_actions(self, raw: str) -> List[Dict]:
        """Parse LLM output into action list."""
        text = raw.strip()
        # Strip markdown code block
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        # Find JSON array
        if "[" in text:
            start = text.index("[")
            end = text.rindex("]") + 1
            data = json.loads(text[start:end])
            if isinstance(data, list):
                # Validate each item has "tool"
                return [a for a in data if isinstance(a, dict) and "tool" in a]

        # Maybe single object
        if "{" in text:
            start = text.index("{")
            end = text.rindex("}") + 1
            data = json.loads(text[start:end])
            if isinstance(data, dict) and "tool" in data:
                return [data]

        return []
