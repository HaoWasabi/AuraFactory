"""Bilingual message templates — responds in the same language as user input."""

MESSAGES = {
    "request_locked": {
        "vi": "⏳ Bạn có 1 yêu cầu đang xử lý — xử lý xong đã nhé.",
        "en": "⏳ You have an active request — please wait for it to finish.",
    },
    "clarify": {
        "vi": "🤔 Bạn có thể mô tả cụ thể hơn được không? Ví dụ: tạo những channel gì, cho ai, trong category nào?",
        "en": "🤔 Could you be more specific? For example: what channels to create, for whom, in which category?",
    },
    "out_of_scope": {
        "vi": "❌ Yêu cầu này nằm ngoài phạm vi AuraFactory. Tôi chỉ hỗ trợ quản lý Discord server (channels, roles, permissions, moderation).",
        "en": "❌ This request is outside AuraFactory's scope. I only help with Discord server management (channels, roles, permissions, moderation).",
    },
    "plan_failed": {
        "vi": "❌ Không tạo được kế hoạch: {error}",
        "en": "❌ Failed to create plan: {error}",
    },
    "plan_header_approval": {
        "vi": "📋 **Kế hoạch** (risk: {risk})\n{plan_text}\n\n⚠️ Cần bạn duyệt trước khi thực thi:",
        "en": "📋 **Plan** (risk: {risk})\n{plan_text}\n\n⚠️ Needs your approval before execution:",
    },
    "plan_header_auto": {
        "vi": "📋 **Kế hoạch** (auto-approved)\n{plan_text}\n\n⏳ Đang thực thi...",
        "en": "📋 **Plan** (auto-approved)\n{plan_text}\n\n⏳ Executing...",
    },
    "exec_completed": {
        "vi": "✅ **Hoàn thành!** {done}/{total} bước thành công.",
        "en": "✅ **Done!** {done}/{total} steps completed successfully.",
    },
    "exec_partial": {
        "vi": "⚠️ **Thực thi dừng** tại bước {failed}/{total}: {error}",
        "en": "⚠️ **Execution stopped** at step {failed}/{total}: {error}",
    },
    "exec_error": {
        "vi": "⚠️ **Lỗi:** {error} ({done}/{total} bước hoàn thành)",
        "en": "⚠️ **Error:** {error} ({done}/{total} steps completed)",
    },
    "approved": {
        "vi": "✅ Đã duyệt! Đang thực thi...",
        "en": "✅ Approved! Executing...",
    },
    "rejected": {
        "vi": "🚫 Đã hủy kế hoạch.",
        "en": "🚫 Plan cancelled.",
    },
    "only_creator_approve": {
        "vi": "❌ Chỉ người tạo yêu cầu mới được duyệt.",
        "en": "❌ Only the request creator can approve.",
    },
    "only_creator_reject": {
        "vi": "❌ Chỉ người tạo yêu cầu mới được từ chối.",
        "en": "❌ Only the request creator can reject.",
    },
    "query_error": {
        "vi": "⚠️ Xin lỗi, tôi không thể trả lời câu hỏi này lúc này. Vui lòng thử lại sau.",
        "en": "⚠️ Sorry, I can't answer this question right now. Please try again later.",
    },
    "query_no_info": {
        "vi": "Tôi không tìm thấy thông tin phù hợp để trả lời câu hỏi của bạn. Bạn có thể hỏi cụ thể hơn được không?",
        "en": "I couldn't find relevant information to answer your question. Could you be more specific?",
    },
    "bot_not_installed": {
        "vi": "⚠️ Bot chưa được mời vào server này. Vui lòng mời bot trước:\n{invite_url}",
        "en": "⚠️ Bot hasn't been added to this server yet. Please invite the bot first:\n{invite_url}",
    },
    "bot_not_installed_short": {
        "vi": "⚠️ Server này chưa kích hoạt AuraFactory. Vui lòng mời bot vào server trước khi sử dụng.",
        "en": "⚠️ This server hasn't activated AuraFactory yet. Please add the bot to your server first.",
    },
    "plan_not_found": {
        "vi": "Plan không tồn tại.",
        "en": "Plan not found.",
    },
    "plan_not_pending": {
        "vi": "Plan không ở trạng thái chờ duyệt (hiện tại: {status}).",
        "en": "Plan is not in pending state (current: {status}).",
    },
    "only_creator_can_approve": {
        "vi": "Chỉ người tạo yêu cầu mới được phê duyệt.",
        "en": "Only the request creator can approve.",
    },
    "only_creator_can_reject": {
        "vi": "Chỉ người tạo yêu cầu mới được từ chối.",
        "en": "Only the request creator can reject.",
    },
}


def msg(key: str, lang: str = "vi", **kwargs) -> str:
    """Get a message in the specified language.
    
    Args:
        key: Message key from MESSAGES dict.
        lang: Language code ('vi' or 'en'). Defaults to 'vi'.
        **kwargs: Format variables for the message template.
    
    Returns:
        Formatted message string.
    """
    template = MESSAGES.get(key, {})
    text = template.get(lang, template.get("vi", f"[{key}]"))
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text
