# agents/architect_agent.py
"""
Architect Agent — "Kiến trúc sư Server"
Agentic AI Lens: Autonomy Level 1-2 (bounded)

Responsibilities:
- Tạo/sửa/xóa channels
- Tạo/xóa categories  
- Bulk operations

Constraints:
- CHỈ được dùng discord_channel, discord_category tools
- Delete/bulk operations → cần approval (handled by BaseAgent)
"""
import time
import json
from typing import Dict, Any, Optional
from agents.base_agent import BaseAgent
from providers.base import LLMProvider
from schemas.contracts import AgentRole, TaskAssignment, TaskResult, TaskStatus
from observability.tracer import Tracer
from tools.discord_channel import DiscordChannel
from tools.discord_category import DiscordCategory


class ArchitectAgent(BaseAgent):
    """
    Specialist: Discord workspace structure.
    Wraps existing DiscordChannel + DiscordCategory tools.
    """
    
    def __init__(self, llm: LLMProvider, tracer: Tracer):
        super().__init__(
            role=AgentRole.ARCHITECT,
            llm=llm,
            tracer=tracer,
            system_prompt="You are the Architect Agent. Execute Discord structure operations.",
            max_retries=2,
        )
        # Tool mapping — tên action → function thực thi
        self._tool_map = {
            "create_channel": self._create_channel,
            "modify_channel": self._modify_channel,
            "delete_channel": self._delete_channel,
            "create_category": self._create_category,
            "delete_category": self._delete_category,
            "bulk_create_channels": self._bulk_create_channels,
        }
    
    async def _execute(self, task: TaskAssignment, trace_id: str, guild=None) -> TaskResult:
        """Route action tới đúng tool function"""
        
        action = task.action
        params = task.parameters
        
        if action not in self._tool_map:
            return TaskResult(
                task_id=task.task_id,
                agent=self.role,
                status=TaskStatus.FAILED,
                error_message=f"Unknown action: {action}. Available: {list(self._tool_map.keys())}",
            )
        
        if guild is None:
            return TaskResult(
                task_id=task.task_id,
                agent=self.role,
                status=TaskStatus.FAILED,
                error_message="Guild object is required for Discord operations",
            )
        
        # Execute tool
        self._log_reasoning(trace_id, f"Executing {action} with params: {params}")
        
        start = time.time()
        tool_fn = self._tool_map[action]
        result_str = await tool_fn(guild, params)
        duration = (time.time() - start) * 1000
        
        # Parse result
        try:
            result_data = json.loads(result_str)
        except json.JSONDecodeError:
            result_data = {"raw": result_str}
        
        # Log tool call
        self._log_tool_call(trace_id, action, params, result_data, duration)
        
        # Determine status
        status = TaskStatus.SUCCESS if result_data.get("status") == "success" else TaskStatus.FAILED
        
        return TaskResult(
            task_id=task.task_id,
            agent=self.role,
            status=status,
            output=result_data,
            error_message=result_data.get("message", "") if status == TaskStatus.FAILED else "",
        )
    
    # === Tool wrappers (delegate to existing DiscordChannel/Category) ===
    
    async def _create_channel(self, guild, params: Dict) -> str:
        """Wrap existing DiscordChannel.create_channel"""
        name = params.get("channel_name", params.get("name", "new-channel"))
        ch_type = params.get("channel_type", params.get("type", "text"))
        # Pass remaining params as kwargs
        kwargs = {k: v for k, v in params.items() if k not in ("channel_name", "name", "channel_type", "type")}
        return await DiscordChannel.create_channel(guild, name, ch_type, **kwargs)
    
    async def _modify_channel(self, guild, params: Dict) -> str:
        """Wrap existing DiscordChannel.modify_channel"""
        channel_id = params.get("channel_id")
        if not channel_id:
            return json.dumps({"status": "error", "message": "channel_id is required"})
        kwargs = {k: v for k, v in params.items() if k != "channel_id"}
        return await DiscordChannel.modify_channel(guild, int(channel_id), **kwargs)
    
    async def _delete_channel(self, guild, params: Dict) -> str:
        """Wrap existing DiscordChannel.delete_channel_or_category"""
        target_id = params.get("channel_id", params.get("target_id"))
        
        # Nếu không có ID, tìm channel bằng tên
        if not target_id:
            channel_name = params.get("channel_name", params.get("name", ""))
            if not channel_name:
                return json.dumps({"status": "error", "message": "Cần channel_id hoặc channel_name"}, ensure_ascii=False)
            # Tìm channel by name trong guild
            found = None
            for ch in guild.channels:
                if ch.name.lower() == channel_name.lower().replace(" ", "-"):
                    found = ch
                    break
            if not found:
                return json.dumps({"status": "error", "message": f"Không tìm thấy kênh '{channel_name}'"}, ensure_ascii=False)
            target_id = found.id
        
        reason = params.get("reason", "AI Agent Request")
        return await DiscordChannel.delete_channel_or_category(guild, int(target_id), reason)
    
    async def _create_category(self, guild, params: Dict) -> str:
        """Wrap existing DiscordCategory"""
        name = params.get("category_name", params.get("name", "New Category"))
        kwargs = {k: v for k, v in params.items() if k not in ("category_name", "name")}
        # DiscordCategory should have similar interface
        return await DiscordCategory.create_category(guild, name, **kwargs)
    
    async def _delete_category(self, guild, params: Dict) -> str:
        """Delete category"""
        target_id = params.get("category_id", params.get("target_id"))
        if not target_id:
            return json.dumps({"status": "error", "message": "category_id is required"})
        return await DiscordChannel.delete_channel_or_category(guild, int(target_id), "AI Agent Request")
    
    async def _bulk_create_channels(self, guild, params: Dict) -> str:
        """Tạo nhiều channels cùng lúc"""
        channels = params.get("channels", [])
        results = []
        for ch in channels:
            name = ch.get("name", "channel")
            ch_type = ch.get("type", "text")
            kwargs = {k: v for k, v in ch.items() if k not in ("name", "type")}
            r = await DiscordChannel.create_channel(guild, name, ch_type, **kwargs)
            results.append(json.loads(r))
        
        success_count = sum(1 for r in results if r.get("status") == "success")
        return json.dumps({
            "status": "success" if success_count > 0 else "error",
            "action": "bulk_create_channels",
            "total": len(channels),
            "success": success_count,
            "failed": len(channels) - success_count,
            "details": results,
        }, ensure_ascii=False)
