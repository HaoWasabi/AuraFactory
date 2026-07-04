# providers/bedrock_provider.py
"""
Phase 2: AWS Bedrock Provider — CHƯA CẦN DÙNG NGAY.
Khi ready, chỉ cần:
  1. pip install boto3
  2. Đổi config: PROVIDER=bedrock
  3. Agent code KHÔNG thay đổi gì.
"""
import time
from typing import List, Dict, Any, Optional
from providers.base import LLMProvider, LLMResponse


class BedrockProvider(LLMProvider):
    """
    AWS Bedrock implementation — Phase 2
    Uncomment và dùng khi tích hợp AWS.
    """
    
    def __init__(self, model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0", region: str = "us-east-1"):
        # import boto3
        # self._client = boto3.client('bedrock-runtime', region_name=region)
        self._model_id = model_id
        self._region = region
        raise NotImplementedError(
            "BedrockProvider chưa active. Dùng GeminiProvider cho Phase 1. "
            "Khi ready AWS, bỏ raise này và uncomment boto3."
        )
    
    @property
    def model_name(self) -> str:
        return self._model_id
    
    async def generate(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        tools: Optional[List[Dict]] = None,
    ) -> LLMResponse:
        """Bedrock Converse API"""
        # start = time.time()
        # response = self._client.converse(
        #     modelId=self._model_id,
        #     messages=[{"role": m["role"], "content": [{"text": m["content"]}]} for m in messages],
        #     system=[{"text": system_prompt}] if system_prompt else [],
        #     inferenceConfig={"temperature": temperature, "maxTokens": max_tokens},
        # )
        # return LLMResponse(
        #     content=response['output']['message']['content'][0]['text'],
        #     model=self._model_id,
        #     input_tokens=response['usage']['inputTokens'],
        #     output_tokens=response['usage']['outputTokens'],
        #     latency_ms=(time.time() - start) * 1000,
        #     raw_response=response,
        # )
        raise NotImplementedError("Phase 2 — chưa active")
    
    async def generate_with_tools(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str,
        tools: List[Dict],
        temperature: float = 0.3,
    ) -> Dict[str, Any]:
        """Bedrock Converse API with toolUse"""
        # Bedrock format tools khác Gemini nhưng interface giữ nguyên
        # bedrock_tools = [{"toolSpec": {"name": t["name"], "description": t["description"], 
        #                   "inputSchema": {"json": t["parameters"]}}} for t in tools]
        # response = self._client.converse(
        #     modelId=self._model_id,
        #     messages=[...],
        #     system=[{"text": system_prompt}],
        #     toolConfig={"tools": bedrock_tools},
        # )
        # ... parse toolUse blocks ...
        raise NotImplementedError("Phase 2 — chưa active")
