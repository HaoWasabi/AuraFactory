"""UnifiedAgent v2 — Spec-driven orchestrator with Graph-based tool retrieval.

Flow:
    1. User request arrives
    2. ToolGraph.retrieve_tools(query, k=5) → top-k relevant tools + schemas
    3. Build focused prompt: system + tools schemas + guild context + request
    4. LLM call → structured plan (steps with tool_name + kwargs)
    5. Execute plan steps via MCP (kwargs spread directly into connectors)

Key differences from v1:
    - No separate classifier LLM call (graph replaces it)
    - ~90% token savings (only top-k tools in context, not all 80+)
    - Spec-driven: all validation/schema from single YAML
    - kwargs pattern: clean tool code, no hardcoded params
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from app.core.spec_loader import SpecRegistry
from app.core.tool_graph import ToolGraph
from app.core.kwargs_filter import KwargsFilter

logger = logging.getLogger(__name__)


class UnifiedAgentV2:
    """Main orchestrator for AuraFactory Discord AI Agent.

    Integrates: SpecRegistry + ToolGraph + KwargsFilter + LLM + MCP

    Usage:
        registry = SpecRegistry.load()
        graph = ToolGraph(registry)
        agent = UnifiedAgentV2(registry, graph, llm_client, mcp_server)
        response = await agent.process(request, guild_context)
    """

    def __init__(
        self,
        registry: SpecRegistry,
        graph: ToolGraph,
        llm_client: Any,  # LLM interface (Gemini, Bedrock, etc.)
        mcp_server: Any,  # MCP server for tool execution
        top_k: int = 5,
    ) -> None:
        self._registry = registry
        self._graph = graph
        self._filter = KwargsFilter(registry)
        self._llm = llm_client
        self._mcp = mcp_server
        self._top_k = top_k

    async def process(
        self,
        user_request: str,
        guild_context: Dict[str, Any],
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Main entry point — process a user request end-to-end.

        Args:
            user_request: Natural language request from user.
            guild_context: Current guild state (id, name, features, etc.).
            conversation_history: Previous messages for context.

        Returns:
            Dict with response text, actions taken, and any errors.
        """
        # Step 1: Retrieve relevant tools via graph (FREE, <5ms)
        relevant_tools = self._graph.retrieve_tools(user_request, k=self._top_k)

        if not relevant_tools:
            # Fallback: if graph returns nothing, might be a general question
            return await self._handle_no_tools(user_request, guild_context, conversation_history)

        # Step 2: Build focused prompt
        prompt = self._build_prompt(
            user_request=user_request,
            tools=relevant_tools,
            guild_context=guild_context,
            conversation_history=conversation_history,
        )

        # Step 3: LLM call → get plan
        llm_response = await self._llm.generate(prompt)
        plan = self._parse_plan(llm_response)

        if plan is None:
            # LLM decided no tool call needed — just a text response
            return {
                "response": llm_response.text if hasattr(llm_response, 'text') else str(llm_response),
                "actions": [],
                "tool_calls": 0,
            }

        # Step 4: Execute plan steps via MCP
        results = await self._execute_plan(plan, guild_context)

        # Step 5: Format final response
        return self._format_response(plan, results, user_request)

    # ------------------------------------------------------------------
    # Prompt Building
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        user_request: str,
        tools: List[Dict[str, Any]],
        guild_context: Dict[str, Any],
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """Build focused LLM prompt with only relevant tools.

        This is where the token savings happen — instead of 80+ tools × ~300 tokens,
        we only include 3-5 tools × ~300 tokens.
        """
        # System instruction
        system = self._get_system_prompt()

        # Tools section — only top-k
        tools_section = "## Available Tools\n\n"
        for tool in tools:
            schema = tool.get("schema", {})
            tools_section += f"### {tool['name']}\n"
            tools_section += f"Description: {tool['description']}\n"
            tools_section += f"Risk: {tool['risk_level']}\n"

            if tool.get("prerequisites"):
                tools_section += f"Prerequisites: {', '.join(tool['prerequisites'])}\n"
            if tool.get("constraints"):
                tools_section += f"Constraints: {'; '.join(tool['constraints'])}\n"

            # Parameters
            params = schema.get("parameters", {}).get("properties", {})
            required = schema.get("parameters", {}).get("required", [])
            if params:
                tools_section += "Parameters:\n"
                for p_name, p_def in params.items():
                    req_marker = " (REQUIRED)" if p_name in required else ""
                    desc = p_def.get("description", "")
                    p_type = p_def.get("type", "string")
                    enum = p_def.get("enum", [])
                    enum_str = f" | enum: {enum}" if enum else ""
                    tools_section += f"  - {p_name}: {p_type}{req_marker} — {desc}{enum_str}\n"
            tools_section += "\n"

        # Guild context section
        guild_section = "## Current Guild State\n"
        guild_section += f"Guild: {guild_context.get('name', 'Unknown')} (ID: {guild_context.get('id', '')})\n"
        if guild_context.get("features"):
            guild_section += f"Features: {', '.join(guild_context['features'])}\n"
        guild_section += "\n"

        # Conversation history
        history_section = ""
        if conversation_history:
            history_section = "## Conversation History\n"
            for msg in conversation_history[-5:]:  # Last 5 messages
                role = msg.get("role", "user")
                content = msg.get("content", "")
                history_section += f"{role}: {content}\n"
            history_section += "\n"

        # User request
        request_section = f"## User Request\n{user_request}\n"

        # Response format instruction
        format_section = """
## Response Format

If tool calls are needed, respond with a JSON plan:
```json
{
  "thinking": "Brief reasoning about what to do",
  "steps": [
    {
      "tool": "discord.module.action",
      "kwargs": {"param1": "value1", "param2": 123},
      "description": "What this step does"
    }
  ],
  "response_template": "Message to show user after execution"
}
```

If no tool calls are needed (general question, clarification), respond with plain text.

Rules:
- Only use tools from the Available Tools section above.
- Only use parameters listed in each tool's Parameters.
- For multi-step tasks, reference previous step results with $step_N.field_name.
- If a prerequisite tool is listed, include it as an earlier step.
- Respond in the same language the user used.
"""

        full_prompt = f"{system}\n\n{tools_section}\n{guild_section}\n{history_section}\n{request_section}\n{format_section}"
        return full_prompt

    def _get_system_prompt(self) -> str:
        """Core system prompt for the agent."""
        return """You are AuraFactory, an advanced AI agent for Discord server management.

Your role:
- Understand the user's intent and plan the necessary actions.
- Use the provided tools to execute Discord operations.
- Be precise with parameters — only pass what's needed.
- For destructive actions (delete, ban, kick), confirm the target exists first.
- Chain multiple tools when needed (e.g., list roles → assign role).

You have access to a SUBSET of tools relevant to this request.
Do NOT hallucinate tool names or parameters not listed below.
"""

    # ------------------------------------------------------------------
    # Plan Parsing
    # ------------------------------------------------------------------

    def _parse_plan(self, llm_response: Any) -> Optional[Dict[str, Any]]:
        """Extract structured plan from LLM response.

        Returns None if LLM decided no tool call is needed.
        """
        # Get text from response
        text = llm_response.text if hasattr(llm_response, 'text') else str(llm_response)

        # Try to extract JSON from response
        try:
            # Look for ```json ... ``` block
            if "```json" in text:
                json_str = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                json_str = text.split("```")[1].split("```")[0].strip()
            elif text.strip().startswith("{"):
                json_str = text.strip()
            else:
                # No JSON found — treat as plain text response
                return None

            plan = json.loads(json_str)

            # Validate plan structure
            if "steps" in plan and isinstance(plan["steps"], list):
                return plan

            return None

        except (json.JSONDecodeError, IndexError, KeyError) as e:
            logger.warning("Failed to parse LLM plan: %s", e)
            return None

    # ------------------------------------------------------------------
    # Plan Execution
    # ------------------------------------------------------------------

    async def _execute_plan(
        self,
        plan: Dict[str, Any],
        guild_context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Execute plan steps sequentially via MCP.

        Handles $step_N.field references between steps.
        """
        results: List[Dict[str, Any]] = []
        step_outputs: List[Dict[str, Any]] = []

        for i, step in enumerate(plan.get("steps", [])):
            tool_name = step.get("tool", "")
            kwargs = step.get("kwargs", {})

            # Resolve $step_N references
            kwargs = self._resolve_references(kwargs, step_outputs)

            # Add guild_id if not present
            if "guild_id" not in kwargs:
                kwargs["guild_id"] = guild_context.get("id")

            # Runtime filter — drop hallucinated params
            context = kwargs.pop("type", None) if "type" in kwargs else None
            clean_kwargs = self._filter.validate_and_coerce(tool_name, kwargs, context)
            if context:
                clean_kwargs["type"] = context

            # Check dependency warnings
            warnings = self._filter.check_dependencies(tool_name, clean_kwargs, context)
            if warnings:
                logger.warning("Step %d dependency warnings: %s", i, warnings)

            # Execute via MCP
            try:
                result = await self._mcp.execute(tool_name=tool_name, **clean_kwargs)
                step_result = {"step": i, "tool": tool_name, "status": "success", "result": result}
            except PermissionError as e:
                step_result = {"step": i, "tool": tool_name, "status": "error", "error": f"Permission denied: {e}"}
            except ValueError as e:
                step_result = {"step": i, "tool": tool_name, "status": "error", "error": f"Validation error: {e}"}
            except Exception as e:
                step_result = {"step": i, "tool": tool_name, "status": "error", "error": str(e)}

            results.append(step_result)
            step_outputs.append(step_result.get("result", {}))

            # Stop execution on critical error
            if step_result["status"] == "error":
                spec = self._registry.get_tool(tool_name)
                if spec and spec.risk_level in ("high", "critical"):
                    logger.error("Stopping plan execution due to error in high-risk tool: %s", tool_name)
                    break

        return results

    def _resolve_references(
        self,
        kwargs: Dict[str, Any],
        step_outputs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Resolve $step_N.field_name references in kwargs.

        Example: "$step_0.id" → step_outputs[0]["id"]
        """
        resolved = {}
        for key, value in kwargs.items():
            if isinstance(value, str) and value.startswith("$step_"):
                try:
                    parts = value[1:].split(".", 1)  # "step_0.id" → ["step_0", "id"]
                    step_idx = int(parts[0].replace("step_", ""))
                    field = parts[1] if len(parts) > 1 else None

                    if 0 <= step_idx < len(step_outputs):
                        output = step_outputs[step_idx]
                        if field and isinstance(output, dict):
                            resolved[key] = output.get(field, value)
                        else:
                            resolved[key] = output
                    else:
                        resolved[key] = value
                except (ValueError, IndexError):
                    resolved[key] = value
            else:
                resolved[key] = value

        return resolved

    # ------------------------------------------------------------------
    # Response Formatting
    # ------------------------------------------------------------------

    def _format_response(
        self,
        plan: Dict[str, Any],
        results: List[Dict[str, Any]],
        original_request: str,
    ) -> Dict[str, Any]:
        """Format execution results into a user-friendly response."""
        successful = [r for r in results if r["status"] == "success"]
        failed = [r for r in results if r["status"] == "error"]

        response_text = plan.get("response_template", "")

        # If all succeeded
        if not failed and successful:
            if not response_text:
                response_text = f"✅ Completed {len(successful)} action(s) successfully."
        elif failed:
            error_msgs = [f"- {r['tool']}: {r['error']}" for r in failed]
            response_text = f"⚠️ {len(failed)} action(s) failed:\n" + "\n".join(error_msgs)
            if successful:
                response_text += f"\n\n✅ {len(successful)} action(s) succeeded."

        return {
            "response": response_text,
            "actions": results,
            "tool_calls": len(results),
            "thinking": plan.get("thinking", ""),
        }

    async def _handle_no_tools(
        self,
        user_request: str,
        guild_context: Dict[str, Any],
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Handle requests that don't match any tools (general questions)."""
        prompt = f"""You are AuraFactory, an AI assistant for Discord server management.
The user asked a general question that doesn't require any tool execution.
Answer helpfully and concisely.

Guild: {guild_context.get('name', 'Unknown')}
User: {user_request}

Respond in the same language the user used."""

        response = await self._llm.generate(prompt)
        text = response.text if hasattr(response, 'text') else str(response)

        return {
            "response": text,
            "actions": [],
            "tool_calls": 0,
        }
