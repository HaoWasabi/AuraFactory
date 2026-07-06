# tools/discord_webhook.py
import json
import nextcord
import aiohttp
from typing import Optional, Dict, Any, List

class DiscordWebhook:
    """
    Tập hợp các bộ công cụ (Tools) dành cho Agentic AI nhằm quản lý, tạo lập Webhook
    và cấu hình tích hợp tự động các luồng thông báo từ GitHub / GitLab vào Discord Server.
    """

    @staticmethod
    async def create_webhook(guild: nextcord.Guild, channel_id: int, webhook_name: str, avatar_url: Optional[str] = None) -> str:
        """
        Công cụ tạo một Webhook mới tại kênh văn bản được chỉ định.
        Trả về URL của Webhook để Agent có thể đem đi cấu hình ở GitHub/GitLab Settings.
        """
        try:
            channel = guild.get_channel(channel_id)
            if not channel or not isinstance(channel, nextcord.TextChannel):
                return json.dumps({"status": "error", "message": "Không tìm thấy kênh văn bản hợp lệ để tạo Webhook."}, ensure_ascii=False)

            # Kiểm tra quyền tạo Webhook của Bot
            if not channel.permissions_for(guild.me).manage_webhooks:
                return json.dumps({"status": "error", "message": "Bot thiếu quyền 'Manage Webhooks' tại kênh này."}, ensure_ascii=False)

            # Xử lý avatar cho Webhook nếu có
            avatar_bytes = None
            if avatar_url:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(avatar_url, timeout=10) as response:
                            if response.status == 200:
                                avatar_bytes = await response.read()
                except:
                    pass # Bỏ qua nếu lỗi tải ảnh, dùng avatar mặc định

            # Khởi tạo Webhook từ Nextcord API
            webhook = await channel.create_webhook(name=webhook_name, avatar=avatar_bytes, reason="Tạo tự động bởi AI Agent")

            return json.dumps({
                "status": "success",
                "action": "create_webhook",
                "webhook_name": webhook.name,
                "webhook_id": webhook.id,
                "webhook_url": webhook.url,  # URL bí mật này dùng để dán vào GitHub/GitLab
                "channel_id": channel_id,
                "channel_name": channel.name
            }, ensure_ascii=False)

        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot bị từ chối quyền truy cập hệ thống Webhook."}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Thất bại khi tạo Webhook: {str(e)}"}, ensure_ascii=False)

    @staticmethod
    async def execute_webhook_raw(webhook_url: str, content: Optional[str] = None, embeds: Optional[List[Dict[str, Any]]] = None, username: Optional[str] = None, avatar_url: Optional[str] = None) -> str:
        """
        Công cụ bắn tin nhắn trực tiếp qua Webhook URL (Không cần thông qua Bot instance).
        Rất hữu ích khi Agent muốn gửi tin nhắn ẩn danh hoặc giả lập một con bot khác.
        """
        try:
            payload = {}
            if content: payload["content"] = content
            if embeds: payload["embeds"] = embeds
            if username: payload["username"] = username
            if avatar_url: payload["avatar_url"] = avatar_url

            if not content and not embeds:
                return json.dumps({"status": "error", "message": "Nội dung (content) hoặc Embeds không được để trống cùng lúc."}, ensure_ascii=False)

            async with aiohttp.ClientSession() as session:
                async with session.post(webhook_url, json=payload) as response:
                    if response.status in [200, 204]:
                        return json.dumps({"status": "success", "message": "Tin nhắn Webhook đã được gửi đi thành công."}, ensure_ascii=False)
                    else:
                        res_text = await response.text()
                        return json.dumps({"status": "error", "message": f"Discord API từ chối Webhook (Code {response.status}): {res_text}"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Lỗi kết nối gửi Webhook: {str(e)}"}, ensure_ascii=False)

    @staticmethod
    def transform_github_payload(event_type: str, payload_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Bộ chuyển đổi thông minh (Transformer): Nhận dữ liệu thô (JSON) từ GitHub Webhook gửi sang,
        dịch và đóng gói thành cấu trúc Embed Discord siêu đẹp mắt để Agent hiển thị lên server.
        Supports: 'push', 'issues'
        """
        embed = {
            "color": 3447003, # Màu xanh lam của GitHub
            "footer": {"text": "GitHub Integration Tools"}
        }

        if event_type == "push":
            ref = payload_dict.get("ref", "").split("/")[-1]
            repo_name = payload_dict.get("repository", {}).get("full_name", "Unknown Repo")
            pusher = payload_dict.get("pusher", {}).get("name", "Someone")
            compare_url = payload_dict.get("compare", "#")
            
            commits = payload_dict.get("commits", [])
            commit_logs = ""
            for c in commits[:5]: # Lấy tối đa 5 commit gần nhất để tránh tràn tin nhắn
                message = c.get("message", "").split("\n")[0]
                sha = c.get("id", "")[:7]
                commit_logs += f"[`{sha}`] {message} - *by {c.get('author', {}).get('name')}*\n"

            embed["title"] = f"🚀 [GitHub] New Push to `{ref}` in **{repo_name}**"
            embed["url"] = compare_url
            embed["description"] = f"**Pushed by:** {pusher}\n\n**Commits:**\n{commit_logs if commit_logs else 'No commit info.'}"
            embed["color"] = 2067276 # Màu xanh lá cây báo hiệu deploy/push

        elif event_type == "issues":
            action = payload_dict.get("action", "opened")
            issue = payload_dict.get("issue", {})
            repo_name = payload_dict.get("repository", {}).get("full_name", "Unknown Repo")
            
            embed["title"] = f"⚠️ [GitHub] Issue #{issue.get('number')} {action.capitalize()} in **{repo_name}**"
            embed["url"] = issue.get("html_url", "#")
            embed["description"] = f"**Title:** {issue.get('title')}\n**Opened by:** {issue.get('user', {}).get('login')}\n\n*Description:*\n{issue.get('body', 'No description.')[:300]}..."
            embed["color"] = 15158332 # Màu đỏ/cam cảnh báo lỗi

        else:
            embed["title"] = f"📦 [GitHub] Event: {event_type}"
            embed["description"] = f"Nhận được một sự kiện dạng `{event_type}` từ kho lưu trữ GitHub."

        return {"embeds": [embed]}

    @staticmethod
    def transform_gitlab_payload(object_kind: str, payload_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Bộ chuyển đổi thông minh (Transformer): Nhận dữ liệu thô (JSON) từ GitLab Webhook gửi sang,
        dịch và đóng gói thành cấu trúc Embed Discord siêu đẹp mắt.
        Supports: 'push', 'merge_request'
        """
        embed = {
            "color": 15424514, # Màu cam đặc trưng của GitLab
            "footer": {"text": "GitLab Integration Tools"}
        }

        if object_kind == "push":
            ref = payload_dict.get("ref", "").split("/")[-1]
            project_name = payload_dict.get("project", {}).get("path_with_namespace", "Unknown Project")
            user_name = payload_dict.get("user_name", "Someone")
            
            commits = payload_dict.get("commits", [])
            commit_logs = ""
            for c in commits[:5]:
                message = c.get("message", "").split("\n")[0]
                sha = c.get("id", "")[:7]
                commit_logs += f"[`{sha}`] {message}\n"

            embed["title"] = f"🦊 [GitLab] New Push to `{ref}` in **{project_name}**"
            embed["description"] = f"**Pushed by:** {user_name}\n\n**Commits:**\n{commit_logs if commit_logs else 'No commit info.'}"

        elif object_kind == "merge_request":
            attributes = payload_dict.get("object_attributes", {})
            action = attributes.get("action", "opened")
            project_name = payload_dict.get("project", {}).get("path_with_namespace", "Unknown Project")
            
            embed["title"] = f"🔀 [GitLab] Merge Request {action.upper()} in **{project_name}**"
            embed["url"] = attributes.get("url", "#")
            embed["description"] = f"**Title:** {attributes.get('title')}\n**Source:** `{attributes.get('source_branch')}` ➡️ **Target:** `{attributes.get('target_branch')}`\n**Author:** {payload_dict.get('user', {}).get('name')}"
            embed["color"] = 5143321 # Màu xanh tím nước biển

        return {"embeds": [embed]}