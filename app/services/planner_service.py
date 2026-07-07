"""PlannerService — generates execution plan in 1 LLM call (§5.4 step 11)."""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.database import Database
from app.llm.base import BaseLLM
from app.mcp import MCPClient
from app.services.context_service import ContextService

logger = logging.getLogger(__name__)

# Risk ordering for comparison
RISK_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

PLANNER_SYSTEM_PROMPT = """You are AuraFactory's execution planner for Discord server management.

Given:
- The server's current state (categories, channels, roles)
- A list of available tools you can use
- The user's request

Your job: produce an execution plan as a JSON object. The plan must contain:
1. A human-readable description of what will be done
2. An ordered list of steps, each specifying a tool call

IMPORTANT RULES:
- Only use tools from the provided tool list
- Each step must have valid tool_params matching the tool's parameter schema
- Assign a risk_level to each step: LOW (read-only, create), MEDIUM (edit, move), HIGH (delete channel/role, kick), CRITICAL (ban, bulk delete, server settings)
- Steps should be in the correct execution order (e.g., create category before creating channels in it)
- Use the server context to resolve IDs (category_id, role_id, etc.)
- Write step descriptions in the SAME language the user used in their request

Respond with ONLY valid JSON, no markdown fences:
{
  "description": "Human-readable summary of what will be done",
  "steps": [
    {
      "tool_name": "discord.channels.create",
      "tool_params": {"guild_id": 123, "name": "general", "category_id": 456},
      "description": "Tạo channel #general trong category THÔNG BÁO",
      "risk_level": "LOW"
    }
  ]
}"""


class PlannerService:
    """Generates an execution plan from user request using 1 LLM call."""

    def __init__(
        self,
        db: Database,
        llm: BaseLLM,
        mcp_client: MCPClient,
        context_service: ContextService,
    ):
        self.db = db
        self.llm = llm
        self.mcp_client = mcp_client
        self.context_service = context_service

    async def generate_plan(
        self,
        request_id: str,
        guild_id: int,
        user_id: int,
        message: str,
        intent: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> dict:
        """Generate an execution plan for a user request.

        Args:
            request_id: UUID of the request being planned.
            guild_id: Discord guild ID.
            user_id: Discord user ID who made the request.
            message: User's original message.
            intent: Classified intent category (setup, manage, etc.).
            history: Optional conversation history.

        Returns:
            Plan dict with plan_id, description, steps, risk_level, status, auto_approved.
            On failure: {"ok": False, "error": ...}
        """
        try:
            # 1. Get server context
            server_context = await self.context_service.get_server_context(guild_id)

            # 2. Get available tools filtered by intent category
            tools = self.mcp_client.get_tools_for_intent(intent)
            if not tools:
                # Fallback to all tools if no category match
                tools = self.mcp_client.list_all_tools()

            tool_descriptions = [t.to_llm_schema() for t in tools]

            # 3. Build messages for LLM
            user_content = self._build_user_prompt(
                message=message,
                guild_id=guild_id,
                server_context=server_context,
                tool_list=tool_descriptions,
            )

            messages = []
            if history:
                for h in history[-4:]:
                    messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
            messages.append({"role": "user", "content": user_content})

            # 4. Single LLM call
            response = await self.llm.generate(
                messages=messages,
                system_prompt=PLANNER_SYSTEM_PROMPT,
                temperature=0.2,
                max_tokens=8192,
            )

            # 5. Parse LLM response into plan
            plan_data = self._parse_plan_response(response.content)
            if plan_data is None:
                await self._fail_request(request_id, "LLM returned invalid plan JSON")
                return {"ok": False, "error": "Không thể tạo kế hoạch — LLM trả về JSON không hợp lệ."}

            # 6. Calculate overall risk level
            overall_risk = self._calculate_risk(plan_data.get("steps", []))

            # 7. Determine status based on risk
            if overall_risk in ("LOW", "MEDIUM"):
                plan_status = "approved"
                request_status = "planned"
            else:
                plan_status = "awaiting_approval"
                request_status = "awaiting_approval"

            # 8. Insert plan + steps into DB
            plan_id = uuid.uuid4()
            now = datetime.now(timezone.utc)
            steps = plan_data.get("steps", [])

            await self.db.execute(
                """INSERT INTO plans (id, request_id, guild_id, user_id, description, total_steps, risk_level, status, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                plan_id,
                uuid.UUID(request_id),
                guild_id,
                user_id,
                plan_data.get("description", ""),
                len(steps),
                overall_risk,
                plan_status,
                now,
            )

            for idx, step in enumerate(steps):
                step_id = uuid.uuid4()
                await self.db.execute(
                    """INSERT INTO plan_steps (id, plan_id, step_number, tool_name, tool_params, description, risk_level, status)
                       VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, 'pending')""",
                    step_id,
                    plan_id,
                    idx + 1,
                    step.get("tool_name", ""),
                    json.dumps(step.get("tool_params", {})),
                    step.get("description", ""),
                    step.get("risk_level", "MEDIUM"),
                )

            # 9. Update request status
            await self.db.execute(
                "UPDATE requests SET status = $2 WHERE id = $1",
                uuid.UUID(request_id),
                request_status,
            )

            logger.info(
                "Plan %s generated for request %s — risk=%s status=%s steps=%d",
                plan_id, request_id, overall_risk, plan_status, len(steps),
            )

            return {
                "ok": True,
                "plan_id": str(plan_id),
                "request_id": request_id,
                "description": plan_data.get("description", ""),
                "steps": steps,
                "risk_level": overall_risk,
                "status": plan_status,
                "auto_approved": plan_status == "approved",
            }

        except Exception as e:
            logger.exception("Plan generation failed for request %s: %s", request_id, e)
            await self._fail_request(request_id, str(e))
            return {"ok": False, "error": f"Lỗi tạo kế hoạch: {e}"}

    def _build_user_prompt(
        self,
        message: str,
        guild_id: int,
        server_context: dict,
        tool_list: List[Dict[str, Any]],
    ) -> str:
        """Build the user prompt containing context + tools + request."""
        return f"""## Server Context (guild_id: {guild_id})
Categories: {server_context.get('categories', '[]')}
Channels: {server_context.get('channels', '[]')}
Roles: {server_context.get('roles', '[]')}
Server Info: {server_context.get('server_info', '{}')}

## Available Tools
{json.dumps(tool_list, indent=2, ensure_ascii=False)}

## User Request
{message}"""

    def _parse_plan_response(self, content: str) -> Optional[dict]:
        """Parse LLM response into plan dict. Returns None on failure."""
        # Strip common markdown fences
        cleaned = content.strip()
        if cleaned.startswith("```"):
            # Remove ```json ... ``` or ``` ... ```
            lines = cleaned.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # Attempt to repair truncated JSON (missing closing brackets)
            repaired = cleaned
            open_braces = repaired.count('{') - repaired.count('}')
            open_brackets = repaired.count('[') - repaired.count(']')
            repaired += ']' * open_brackets + '}' * open_braces
            try:
                data = json.loads(repaired)
                logger.info("Plan JSON repaired (added %d closing brackets)", open_braces + open_brackets)
            except json.JSONDecodeError:
                logger.warning("Failed to parse plan JSON: %s", cleaned[:200])
                return None

        # Validate structure
        if not isinstance(data, dict):
            return None
        if "steps" not in data or not isinstance(data["steps"], list):
            return None

        # Validate each step
        valid_steps = []
        for step in data["steps"]:
            if not isinstance(step, dict):
                continue
            if "tool_name" not in step:
                continue
            # Normalize risk_level
            risk = step.get("risk_level", "MEDIUM").upper()
            if risk not in RISK_ORDER:
                risk = "MEDIUM"
            step["risk_level"] = risk
            valid_steps.append(step)

        if not valid_steps:
            return None

        data["steps"] = valid_steps
        return data

    def _calculate_risk(self, steps: List[dict]) -> str:
        """Calculate overall risk as the highest risk among all steps."""
        if not steps:
            return "LOW"
        max_risk = max(RISK_ORDER.get(s.get("risk_level", "MEDIUM").upper(), 2) for s in steps)
        for risk_name, risk_val in RISK_ORDER.items():
            if risk_val == max_risk:
                return risk_name
        return "MEDIUM"

    async def _fail_request(self, request_id: str, error: str) -> None:
        """Mark request as failed."""
        try:
            await self.db.execute(
                "UPDATE requests SET status = 'failed', error_message = $2 WHERE id = $1",
                uuid.UUID(request_id),
                error[:500],
            )
        except Exception as e:
            logger.error("Failed to update request status: %s", e)
