# agents/orchestrator.py
"""
Orchestrator Agent — "Bộ não điều phối"
Agentic AI Lens: Autonomy Level 3 (Orchestrator)

Responsibilities:
- Analyze user intent
- Decompose thành sub-tasks
- Route tới specialist agents
- Aggregate results

Constraints:
- KHÔNG trực tiếp gọi Discord API
- KHÔNG trực tiếp trả lời user (trừ khi routing decision)
"""
import json
import time
from typing import Dict, Any, List, Optional
from agents.base_agent import BaseAgent
from providers.base import LLMProvider
from schemas.contracts import (
    AgentRole, TaskAssignment, TaskResult, TaskStatus, AgentMessage
)
from observability.tracer import Tracer
from uuid import uuid4


# Orchestrator system prompt — versioned, reviewable (Principle 3: Behavior as Code)
ORCHESTRATOR_SYSTEM_PROMPT = """Bạn là Orchestrator Agent của AuraFactory — hệ thống AI quản trị Discord server.

## Role
Bạn là bộ não điều phối. Bạn KHÔNG BAO GIỜ thực hiện action trực tiếp.
Bạn chỉ: phân tích → lập kế hoạch → giao việc → tổng hợp kết quả.

## Specialist Agents Available
1. **architect**: Tạo/sửa/xóa channel, category. Tools: discord_channel, discord_category
2. **moderator**: Quản lý member (kick, ban, timeout), AutoMod. Tools: discord_member, discord_features  
3. **devops**: Roles, Webhooks, Backup/Restore. Tools: discord_role, discord_webhook, discord_backup

## Output Format (BẮT BUỘC JSON)
Trả về JSON array các tasks cần thực hiện:
```json
{
  "plan_summary": "Tóm tắt kế hoạch 1 dòng",
  "tasks": [
    {
      "agent": "architect|moderator|devops",
      "action": "tên_tool_cần_gọi",
      "parameters": {"key": "value"},
      "priority": "high|medium|low",
      "success_criteria": "Điều kiện thành công"
    }
  ]
}
```

## Rules
- Nếu request liên quan nhiều agent → chia thành nhiều tasks, SẮP XẾP theo dependency
- Nếu action nguy hiểm (xóa, ban) → ghi rõ trong plan để trigger approval
- Nếu không hiểu request → trả {"tasks": [], "plan_summary": "Cần làm rõ: [câu hỏi]"}
- KHÔNG hallucinate tools không tồn tại
"""


class OrchestratorAgent(BaseAgent):
    """
    Orchestrator — phân tích user request, route tới đúng agent.
    """
    
    def __init__(self, llm: LLMProvider, tracer: Tracer):
        super().__init__(
            role=AgentRole.ORCHESTRATOR,
            llm=llm,
            tracer=tracer,
            system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        )
        # Registry các specialist agents
        self._specialists: Dict[str, BaseAgent] = {}
    
    def register_agent(self, role: str, agent: BaseAgent):
        """Đăng ký specialist agent vào registry"""
        self._specialists[role] = agent
    
    async def process_request(self, user_message: str, trace_id: str, guild=None) -> Dict[str, Any]:
        """
        Main entry point — nhận message từ user, trả kết quả.
        
        Flow:
        1. LLM phân tích → plan (JSON)
        2. Với mỗi task trong plan → route tới specialist
        3. Specialist execute (hoặc ask approval)
        4. Aggregate results → trả user
        """
        # Step 1: Reasoning — LLM decompose task
        self._log_reasoning(trace_id, f"Analyzing user request: '{user_message[:100]}...'")
        
        plan = await self._create_plan(user_message, trace_id)
        
        if not plan.get("tasks"):
            return {
                "status": "clarification_needed",
                "message": plan.get("plan_summary", "Không hiểu yêu cầu, vui lòng nói rõ hơn."),
                "trace_id": trace_id,
            }
        
        self._log_reasoning(trace_id, f"Plan: {plan['plan_summary']} ({len(plan['tasks'])} tasks)")
        
        # Step 2: Execute tasks sequentially (respect dependencies)
        results = []
        for i, task_def in enumerate(plan["tasks"]):
            target_agent = task_def.get("agent", "")
            
            # Validate agent exists
            if target_agent not in self._specialists:
                results.append({
                    "task_index": i,
                    "status": "error",
                    "message": f"Agent '{target_agent}' not found in registry",
                })
                continue
            
            # Create TaskAssignment (Explicit Contract)
            task = TaskAssignment(
                task_id=f"{trace_id}-{i}",
                target_agent=AgentRole(target_agent),
                action=task_def.get("action", ""),
                parameters=task_def.get("parameters", {}),
                priority=task_def.get("priority", "medium"),
                success_criteria=task_def.get("success_criteria", ""),
                context=user_message,
            )
            
            # Log handoff
            self.tracer.log_handoff(trace_id, "orchestrator", target_agent, task.action)
            
            # Execute via specialist
            specialist = self._specialists[target_agent]
            result = await specialist.execute_task(task, trace_id, guild)
            results.append(result.to_dict())
        
        # Step 3: Aggregate
        return {
            "status": "completed",
            "plan": plan["plan_summary"],
            "results": results,
            "trace_id": trace_id,
        }
    
    async def _create_plan(self, user_message: str, trace_id: str) -> Dict:
        """Gọi LLM để decompose user request thành plan"""
        start = time.time()
        
        response = await self.llm.generate(
            messages=[{"role": "user", "content": user_message}],
            system_prompt=self.system_prompt,
            temperature=0.2,  # Low temperature for structured output
        )
        
        # Log LLM call
        self._log_tool_call(
            trace_id, "llm_planning",
            {"user_message": user_message[:200]},
            {"response_preview": response.content[:200]},
            duration_ms=response.latency_ms,
        )
        
        # Parse JSON from response
        try:
            # Tìm JSON trong response (có thể có text wrapper)
            content = response.content
            # Thử parse trực tiếp
            if "{" in content:
                json_start = content.index("{")
                json_end = content.rindex("}") + 1
                plan = json.loads(content[json_start:json_end])
                return plan
        except (json.JSONDecodeError, ValueError) as e:
            self.tracer.log_error(trace_id, "orchestrator", f"Failed to parse plan JSON: {e}")
            return {"plan_summary": "Lỗi parse kế hoạch", "tasks": []}
        
        return {"plan_summary": "No plan generated", "tasks": []}
    
    async def _execute(self, task: TaskAssignment, trace_id: str, guild=None) -> TaskResult:
        """Orchestrator không execute tool trực tiếp — chỉ route"""
        return TaskResult(
            task_id=task.task_id,
            agent=self.role,
            status=TaskStatus.FAILED,
            error_message="Orchestrator does not execute tools directly",
        )
