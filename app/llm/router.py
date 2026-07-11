"""LLM Router — điều phối provider và xử lý fallback tự động.

Khi Active_Provider là bedrock và gặp lỗi kết nối/quota, tự động
thử lại bằng Gemini fallback (nếu LLM_FALLBACK_ENABLED=true).
Tuân thủ interface BaseLLM để các service không cần thay đổi code.
"""
import logging
from typing import Any, Dict, List, Optional

from .base import BaseLLM, LLMResponse, LLMQuotaError

logger = logging.getLogger(__name__)

# Các exception của botocore được import lazy để không bắt buộc boto3
_BEDROCK_CATCHABLE: tuple = ()


def _get_bedrock_exceptions() -> tuple:
    global _BEDROCK_CATCHABLE
    if _BEDROCK_CATCHABLE:
        return _BEDROCK_CATCHABLE
    try:
        from botocore.exceptions import ClientError, ConnectionError as BotoConnectionError, EndpointResolutionError
        _BEDROCK_CATCHABLE = (LLMQuotaError, ClientError, BotoConnectionError, EndpointResolutionError)
    except ImportError:
        _BEDROCK_CATCHABLE = (LLMQuotaError,)
    return _BEDROCK_CATCHABLE


class LLMRouter(BaseLLM):
    """Router điều phối giữa Bedrock và Gemini với cơ chế fallback tự động.

    Kế thừa BaseLLM nên có thể drop-in thay thế GeminiLLM / BedrockLLM
    trong tất cả các service mà không cần thay đổi constructor.
    """

    def __init__(
        self,
        primary: BaseLLM,
        fallback: Optional[BaseLLM] = None,
        fallback_enabled: bool = False,
    ) -> None:
        """
        Args:
            primary: Provider chính (BedrockLLM hoặc GeminiLLM).
            fallback: Provider dự phòng Gemini (None nếu không cấu hình).
            fallback_enabled: Có bật cơ chế fallback hay không.
        """
        super().__init__(model=getattr(primary, 'model', ''), api_key='')
        self._primary = primary
        self._fallback = fallback
        self._fallback_enabled = fallback_enabled
        self._fallback_unavailable = False  # True khi chuỗi model fallback đều thất bại

        primary_name = type(primary).__name__
        fallback_name = type(fallback).__name__ if fallback else 'None'
        logger.info(
            "LLMRouter khởi tạo: primary=%s fallback=%s fallback_enabled=%s",
            primary_name, fallback_name, fallback_enabled,
        )

    # ------------------------------------------------------------------
    # BaseLLM interface
    # ------------------------------------------------------------------

    async def generate(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> LLMResponse:
        """Gọi Active_Provider, tự động fallback khi cần."""
        try:
            return await self._primary.generate(
                messages=messages,
                system_prompt=system_prompt,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
        except Exception as exc:
            if not self._should_fallback(exc):
                raise

            # Kiểm tra Gemini API key trước khi fallback
            gemini_key = getattr(self._fallback, 'api_key', '').strip() if self._fallback else ''
            if not gemini_key:
                logger.error(
                    "LLMRouter fallback bị hủy: GEMINI_API_KEY rỗng/không thiết lập. "
                    "Re-raise lỗi gốc từ %s.",
                    type(self._primary).__name__,
                )
                raise

            if self._fallback_unavailable:
                # Chuỗi fallback model đã biết là thất bại — không thử lại
                raise

            logger.warning(
                "LLMRouter fallback: primary=%s lỗi=%s → chuyển sang fallback=%s",
                type(self._primary).__name__,
                type(exc).__name__,
                type(self._fallback).__name__,
            )
            try:
                return await self._fallback.generate(
                    messages=messages,
                    system_prompt=system_prompt,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
            except Exception:
                # Cả hai provider đều thất bại — re-raise lỗi gốc
                raise exc

    # ------------------------------------------------------------------
    # Runtime control
    # ------------------------------------------------------------------

    def switch_provider(self, provider_name: str) -> bool:
        """Chuyển đổi Active_Provider tại runtime.

        Returns:
            True nếu chuyển thành công, False nếu không thể chuyển.
        """
        if provider_name not in ('bedrock', 'gemini'):
            logger.warning("switch_provider: giá trị '%s' không hợp lệ (chấp nhận: bedrock, gemini)", provider_name)
            return False

        if provider_name == 'bedrock':
            from .bedrock import BedrockLLM
            from app.config import settings as _settings
            if not isinstance(self._primary, BedrockLLM) and not isinstance(self._fallback, BedrockLLM):
                logger.warning("switch_provider: BedrockLLM chưa được khởi tạo hoặc ENABLE_BEDROCK_LLM=false — không thể chuyển sang bedrock")
                return False
            # Tìm bedrock instance
            if isinstance(self._primary, BedrockLLM):
                pass  # đã là primary
            else:
                # Swap primary ↔ fallback
                self._primary, self._fallback = self._fallback, self._primary
            logger.info("LLMRouter: đã chuyển Active_Provider sang bedrock")
            return True

        if provider_name == 'gemini':
            from .gemini import GeminiLLM
            if isinstance(self._primary, GeminiLLM):
                logger.info("LLMRouter: Active_Provider đã là gemini")
                return True
            if self._fallback and isinstance(self._fallback, GeminiLLM):
                self._primary, self._fallback = self._fallback, self._primary
                logger.info("LLMRouter: đã chuyển Active_Provider sang gemini")
                return True
            logger.warning("switch_provider: không tìm thấy GeminiLLM instance để chuyển sang")
            return False

        return False

    def update_api_key(self, new_key: str) -> None:
        """Cập nhật Gemini API key tại runtime.

        Cập nhật cả primary (nếu là Gemini) lẫn fallback Gemini.
        """
        if not new_key or not new_key.strip():
            logger.warning("update_api_key: key rỗng hoặc chỉ chứa khoảng trắng — bỏ qua")
            return

        stripped = new_key.strip()
        from .gemini import GeminiLLM
        updated = False
        for provider in (self._primary, self._fallback):
            if provider and isinstance(provider, GeminiLLM):
                provider.update_api_key(stripped)
                updated = True
        if updated:
            logger.info("LLMRouter: Gemini API key đã được cập nhật")
        else:
            logger.warning("update_api_key: không tìm thấy GeminiLLM instance nào")

    # ------------------------------------------------------------------
    # Status helpers (dùng bởi API endpoint /admin/llm-status)
    # ------------------------------------------------------------------

    @property
    def active_provider(self) -> str:
        """Tên provider đang active: 'bedrock' hoặc 'gemini'."""
        from .bedrock import BedrockLLM
        return 'bedrock' if isinstance(self._primary, BedrockLLM) else 'gemini'

    @property
    def gemini_key_configured(self) -> bool:
        """True nếu Gemini API key không rỗng."""
        from .gemini import GeminiLLM
        for p in (self._primary, self._fallback):
            if p and isinstance(p, GeminiLLM):
                return bool(getattr(p, 'api_key', '').strip())
        return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _should_fallback(self, exc: Exception) -> bool:
        """Kiểm tra có nên fallback không."""
        if not self._fallback_enabled:
            return False
        if self._fallback is None:
            return False
        # Chỉ fallback khi active_provider là bedrock
        from .bedrock import BedrockLLM
        if not isinstance(self._primary, BedrockLLM):
            return False
        catchable = _get_bedrock_exceptions()
        return isinstance(exc, catchable)
