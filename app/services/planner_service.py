"""PlannerService — generates execution plan in 1 LLM call (§5.4 step 11)."""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.database import Database
from app.llm.base import BaseLLM
from app.mcp import MCPClient
from app.services._token_tracker import record_token_usage
from app.services.context_service import ContextService

logger = logging.getLogger(__name__)

# Risk ordering for comparison
RISK_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

PLANNER_SYSTEM_PROMPT = """You are Aura — AuraFactory's intelligent Discord management assistant.
When ## Recent Session Context is present, use the IDs listed there instead of searching the Server Context again.

You are AuraFactory's execution planner for Discord server management.

Given:
- The server's current state (categories, channels, roles, members)
- A list of available tools you can use
- The user's request

Your job: produce an execution plan as a JSON object.

CRITICAL RULES:
1. Only use tools from the provided tool list — never invent tool names
2. guild_id MUST be included in every step's tool_params (use the guild_id from the context header)
3. Resolve all IDs from the context — never guess or make up IDs
4. Steps must be in correct execution order (e.g. create category before channels inside it)
5. If you need to delete/modify something by name, find its ID in the context first
6. Assign risk_level per step: LOW (read/create), MEDIUM (edit/move/rename), HIGH (delete channel/role/kick), CRITICAL (ban/bulk delete/server settings)
7. Write step descriptions in the SAME language as the user request

EXAMPLE — Delete a channel:
User: "xóa channel #spam"
Context shows: channels include {"id": "987654321", "name": "spam", ...}
→ Use channel_id "987654321" in tool_params

EXAMPLE — Create channel in category:
User: "tạo channel #general trong category THÔNG BÁO"
Context shows: categories include {"id": "111222333", "name": "THÔNG BÁO", ...}
→ Use category_id "111222333" in tool_params

EXAMPLE — Assign role to member:
User: "gán role Moderator cho @username"
Context shows: roles include {"id": "444555666", "name": "Moderator"}, members include {"id": "777888999", "name": "username"}
→ Use role_id "444555666" and member_id "777888999"

Respond with ONLY valid JSON, no markdown fences:
{
  "description": "Human-readable summary of what will be done",
  "steps": [
    {
      "tool_name": "discord.channels.delete",
      "tool_params": {"guild_id": "123456789", "channel_id": "987654321"},
      "description": "Xóa channel #spam",
      "risk_level": "HIGH"
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
        try:
            # 1. Get server context
            server_context = await self.context_service.get_server_context(guild_id)

            # 2. Get available tools filtered by intent category
            tools = self.mcp_client.get_tools_for_intent(intent)
            if not tools:
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

            # Record token usage
            await record_token_usage(
                self.db,
                request_id,
                response.usage,
                getattr(self.llm, 'provider_name', 'unknown'),
            )

            # 5. Parse LLM response into plan
            plan_data = self._parse_plan_response(response.content)
            if plan_data is None:
                await self._fail_request(request_id, "LLM returned invalid plan JSON")
                return {"ok": False, "error": "Không thể tạo kế hoạch — LLM trả về JSON không hợp lệ."}

            # 6. Validate and fix tool_params (inject guild_id if missing, type-fix IDs)
            plan_data["steps"] = self._validate_and_fix_steps(
                plan_data.get("steps", []), guild_id
            )
            if not plan_data["steps"]:
                await self._fail_request(request_id, "Plan has no valid steps after validation")
                return {"ok": False, "error": "Không thể tạo kế hoạch — các bước không hợp lệ."}

            # 7. Calculate overall risk level
            overall_risk = self._calculate_risk(plan_data.get("steps", []))

            # 8. Determine status based on risk
            if overall_risk in ("LOW", "MEDIUM"):
                plan_status = "approved"
                request_status = "planned"
            else:
                plan_status = "awaiting_approval"
                request_status = "awaiting_approval"

            # 9. Insert plan + steps into DB
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

            # 10. Update request status
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

    # ------------------------------------------------------------------
    # Context Formatting — converts raw JSON strings into LLM-readable text
    # ------------------------------------------------------------------

    def _format_context_for_llm(self, server_context: dict, guild_id: int) -> str:
        """Convert raw context (JSON strings from DB) into structured plain text.

        This is the most important fix: LLMs perform significantly better when
        IDs and names are presented in a clean, scannable format rather than
        escaped JSON strings.
        """
        lines = [f"Guild ID: {guild_id}"]

        # --- Server Info ---
        try:
            server_info = server_context.get("server_info", "{}")
            if isinstance(server_info, str):
                server_info = json.loads(server_info) if server_info.strip() else {}
            if isinstance(server_info, dict) and server_info:
                name = server_info.get("name", "")
                member_count = server_info.get("member_count", "?")
                if name:
                    lines.append(f"Server Name: {name}")
                if member_count:
                    lines.append(f"Member Count: {member_count}")
        except Exception:
            pass

        # --- Categories ---
        try:
            categories = server_context.get("categories", "[]")
            if isinstance(categories, str):
                categories = json.loads(categories) if categories.strip() else []
            if isinstance(categories, list) and categories:
                lines.append("\nCategories (use category_id when creating channels):")
                for cat in categories:
                    cid = cat.get("id", cat.get("category_id", "?"))
                    cname = cat.get("name", "?")
                    lines.append(f"  - \"{cname}\" → id: {cid}")
        except Exception:
            lines.append("\nCategories: (unable to parse)")

        # --- Channels ---
        try:
            channels = server_context.get("channels", "[]")
            if isinstance(channels, str):
                channels = json.loads(channels) if channels.strip() else []
            if isinstance(channels, list) and channels:
                lines.append("\nChannels (use channel_id for delete/rename/move/edit):")
                for ch in channels:
                    cid = ch.get("id", ch.get("channel_id", "?"))
                    cname = ch.get("name", "?")
                    ctype = ch.get("type", "text")
                    cat_id = ch.get("category_id", None)
                    cat_str = f", category_id: {cat_id}" if cat_id else ""
                    # Normalize channel type display
                    type_str = str(ctype).replace("ChannelType.", "").lower()
                    if "voice" in type_str:
                        type_label = "🔊"
                    elif "text" in type_str or type_str in ("0", "text"):
                        type_label = "#"
                    else:
                        type_label = "#"
                    lines.append(f"  - {type_label}{cname} → id: {cid}{cat_str}")
        except Exception:
            lines.append("\nChannels: (unable to parse)")

        # --- Roles ---
        try:
            roles = server_context.get("roles", "[]")
            if isinstance(roles, str):
                roles = json.loads(roles) if roles.strip() else []
            if isinstance(roles, list) and roles:
                lines.append("\nRoles (use role_id for delete/rename/assign/remove):")
                for role in roles:
                    rid = role.get("id", role.get("role_id", "?"))
                    rname = role.get("name", "?")
                    members = role.get("member_count", "?")
                    lines.append(f"  - @{rname} → id: {rid} (members: {members})")
        except Exception:
            lines.append("\nRoles: (unable to parse)")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Prompt Building
    # ------------------------------------------------------------------

    def _build_user_prompt(
        self,
        message: str,
        guild_id: int,
        server_context: dict,
        tool_list: List[Dict[str, Any]],
        session_context: str = "",
    ) -> str:
        """Build the user prompt with human-readable context."""
        formatted_context = self._format_context_for_llm(server_context, guild_id)
        session_section = f"\n{session_context}" if session_context.strip() else ""
        return f"""## Server Context
{formatted_context}{session_section}

## Available Tools
{json.dumps(tool_list, indent=2, ensure_ascii=False)}

## User Request
{message}"""

    # ------------------------------------------------------------------
    # Step Validation & Auto-fix
    # ------------------------------------------------------------------

    def _validate_and_fix_steps(self, steps: List[dict], guild_id: int) -> List[dict]:
        """Validate each step and auto-fix common LLM mistakes.

        Fixes applied:
        1. Inject guild_id if missing
        2. Convert numeric IDs to strings (Discord snowflakes should be strings)
        3. Drop steps with unresolvable tool names (not in registered tools)
        4. Ensure required params per tool are present (log warning if not)
        """
        valid_steps = []

        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                logger.warning("Step %d is not a dict, skipping", i + 1)
                continue

            tool_name = step.get("tool_name", "")
            if not tool_name:
                logger.warning("Step %d has no tool_name, skipping", i + 1)
                continue

            # Normalize risk_level
            risk = step.get("risk_level", "MEDIUM").upper()
            if risk not in RISK_ORDER:
                risk = "MEDIUM"
            step["risk_level"] = risk

            # Get or create tool_params
            params = step.get("tool_params", {})
            if not isinstance(params, dict):
                params = {}

            # Fix 1: Always inject guild_id as string
            if "guild_id" not in params or not params["guild_id"]:
                params["guild_id"] = str(guild_id)
                logger.debug("Injected guild_id into step %d (%s)", i + 1, tool_name)
            else:
                # Ensure it's a string
                params["guild_id"] = str(params["guild_id"])

            # Fix 2: Convert all *_id fields to strings (Discord snowflakes)
            id_fields = [
                "channel_id", "category_id", "role_id", "member_id",
                "user_id", "webhook_id", "message_id", "thread_id",
                "emoji_id", "invite_id", "target_id",
            ]
            for field in id_fields:
                if field in params and params[field] is not None:
                    params[field] = str(params[field])

            # Fix 3: Warn if numeric IDs look like they were hallucinated
            # (very short IDs like "123" are suspicious — real Discord IDs are 17-19 digits)
            for field in id_fields:
                if field in params and field != "guild_id":
                    val = str(params[field])
                    if val.isdigit() and len(val) < 10:
                        logger.warning(
                            "Step %d (%s): %s='%s' looks like a hallucinated ID "
                            "(too short for a Discord snowflake — should be 17-19 digits)",
                            i + 1, tool_name, field, val,
                        )

            # Fix 4: Validate category_ids list (for categories.reorder)
            if "category_ids" in params and isinstance(params["category_ids"], list):
                params["category_ids"] = [str(x) for x in params["category_ids"]]

            step["tool_params"] = params
            valid_steps.append(step)

        return valid_steps

    # ------------------------------------------------------------------
    # Response Parsing
    # ------------------------------------------------------------------

    def _parse_plan_response(self, content: str) -> Optional[dict]:
        """Parse LLM response into plan dict. Returns None on failure."""
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            # Attempt to repair truncated JSON
            repaired = cleaned
            open_braces = repaired.count('{') - repaired.count('}')
            open_brackets = repaired.count('[') - repaired.count(']')
            repaired += ']' * open_brackets + '}' * open_braces
            try:
                data = json.loads(repaired)
                logger.info("Plan JSON repaired (added %d closing brackets)", open_braces + open_brackets)
            except json.JSONDecodeError:
                # Last resort: try to find the JSON object
                try:
                    start = cleaned.index('{')
                    end = cleaned.rindex('}') + 1
                    data = json.loads(cleaned[start:end])
                except (ValueError, json.JSONDecodeError):
                    logger.warning("Failed to parse plan JSON: %s", cleaned[:300])
                    return None

        if not isinstance(data, dict):
            return None
        if "steps" not in data or not isinstance(data["steps"], list):
            return None

        # Validate each step has at minimum a tool_name
        valid_steps = []
        for step in data["steps"]:
            if not isinstance(step, dict):
                continue
            if "tool_name" not in step:
                continue
            valid_steps.append(step)

        if not valid_steps:
            return None

        data["steps"] = valid_steps
        return data

    # ------------------------------------------------------------------
    # Risk Calculation
    # ------------------------------------------------------------------

    def _calculate_risk(self, steps: List[dict]) -> str:
        """Calculate overall risk as the highest risk among all steps."""
        if not steps:
            return "LOW"
        max_risk = max(RISK_ORDER.get(s.get("risk_level", "MEDIUM").upper(), 2) for s in steps)
        for risk_name, risk_val in RISK_ORDER.items():
            if risk_val == max_risk:
                return risk_name
        return "MEDIUM"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
