# agents/copilot_agent.py
"""
Copilot Agent — "Trợ lý thông minh"
Agentic AI Lens: Autonomy Level 2 (Autonomous — read-only nên an toàn)

Responsibilities:
- Trả lời câu hỏi về server/community
- Hỗ trợ event management
- Dịch thuật
- General Q&A

Constraints:
- CHỈ read-only operations
- KHÔNG được modify Discord (channel, role, member...)
- An toàn để chạy tự do không cần approval
"""
import time
import json
from typing import Dict, Any, Optional, List
from agents.base_agent import BaseAgent
from providers.base import LLMProvider
from schemas.contracts import AgentRole, TaskAssignment, TaskResult, TaskStatus
from observability.tracer import Tracer


COPILOT_SYSTEM_PROMPT = """Bạn là Copilot Agent của AuraFactory — trợ lý thông minh cho cộng đồng Discord.

## Khả năng
- Trả lời câu hỏi về server, community guidelines
- Hỗ trợ quản lý sự kiện (event)
- Dịch thuật nội dung
- Tóm tắt thông tin

## Constraints  
- Bạn KHÔNG THỂ thay đổi bất cứ gì trên Discord (tạo channel, ban member, etc.)
- Nếu user yêu cầu action mà bạn không thể → nói rõ "Tôi chỉ có thể trả lời câu hỏi, không thể thực hiện thay đổi."

## Style
- Trả lời ngắn gọn, chính xác
- Dùng tiếng Việt
- Friendly nhưng professional
"""


class CopilotAgent(BaseAgent):
    """
    Read-only assistant — trả lời Q&A, events, translate.
    Không cần approval vì không modify gì.
    """
    
    def __init__(self, llm: LLMProvider, tracer: Tracer, knowledge_base: Optional[Any] = None):
        super().__init__(
            role=AgentRole.COPILOT,
            llm=llm,
            tracer=tracer,
            system_prompt=COPILOT_SYSTEM_PROMPT,
            max_retries=1,  # Q&A không cần retry nhiều
        )
        # Phase 1: Simple in-memory knowledge
        # Phase 2: Swap sang Bedrock Knowledge Bases
        self._knowledge_base = knowledge_base
        self._tool_map = {
            "answer_question": self._answer_question,
            "query_knowledge": self._query_knowledge,
            "translate": self._translate,
            "list_events": self._list_events,
        }
    
    async def _execute(self, task: TaskAssignment, trace_id: str, guild=None) -> TaskResult:
        """Execute copilot task"""
        action = task.action
        params = task.parameters
        
        if action not in self._tool_map:
            # Default: treat as Q&A
            action = "answer_question"
            params = {"question": task.context or str(params)}
        
        self._log_reasoning(trace_id, f"Copilot handling: {action}")
        
        start = time.time()
        tool_fn = self._tool_map[action]
        result = await tool_fn(params, trace_id)
        duration = (time.time() - start) * 1000
        
        self._log_tool_call(trace_id, action, params, result, duration)
        
        return TaskResult(
            task_id=task.task_id,
            agent=self.role,
            status=TaskStatus.SUCCESS,
            output=result,
        )
    
    async def _answer_question(self, params: Dict, trace_id: str) -> Dict:
        """Trả lời câu hỏi chung bằng LLM"""
        question = params.get("question", params.get("query", ""))
        
        # Nếu có knowledge base, query trước
        context = ""
        if self._knowledge_base:
            context = await self._query_kb(question)
        
        # Gọi LLM
        messages = [{"role": "user", "content": question}]
        if context:
            # RAG pattern: inject context vào prompt
            augmented_prompt = f"{self.system_prompt}\n\n## Context từ Knowledge Base:\n{context}"
        else:
            augmented_prompt = self.system_prompt
        
        response = await self.llm.generate(
            messages=messages,
            system_prompt=augmented_prompt,
            temperature=0.5,
        )
        
        return {
            "answer": response.content,
            "model": response.model,
            "has_context": bool(context),
        }
    
    async def _query_knowledge(self, params: Dict, trace_id: str) -> Dict:
        """Query knowledge base (Phase 1: local, Phase 2: Bedrock KB)"""
        query = params.get("query", "")
        
        if self._knowledge_base:
            results = await self._query_kb(query)
            return {"results": results, "source": "knowledge_base"}
        
        return {"results": "Knowledge base chưa được cấu hình", "source": "none"}
    
    async def _translate(self, params: Dict, trace_id: str) -> Dict:
        """Dịch text sang ngôn ngữ khác"""
        text = params.get("text", "")
        target_lang = params.get("target_language", "vi")
        
        response = await self.llm.generate(
            messages=[{"role": "user", "content": f"Translate to {target_lang}: {text}"}],
            system_prompt="You are a translator. Only output the translation, nothing else.",
            temperature=0.1,
        )
        
        return {"translated": response.content, "target_language": target_lang}
    
    async def _list_events(self, params: Dict, trace_id: str) -> Dict:
        """List events (Phase 1: placeholder, Phase 2: DynamoDB/Calendar)"""
        # TODO: Integrate với event storage
        return {
            "events": [],
            "message": "Event system chưa được setup. Sẽ tích hợp sau.",
        }
    
    async def _query_kb(self, query: str) -> str:
        """
        Query knowledge base.
        Phase 1: Simple search (in-memory / file-based)
        Phase 2: Bedrock Knowledge Bases retrieve_and_generate()
        """
        # Placeholder — implement khi có KB
        return ""
