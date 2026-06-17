# tools/discord_channel.py
import nextcord
from typing import Optional, Union, Dict, Any
import json

class DiscordChannelTools:
    """
    Tập hợp các bộ công cụ (Tools) dành cho Agentic AI nhằm thao tác tự động 
    với Danh mục (Category) và Kênh (Channels) trên hệ thống Discord.
    """

    @staticmethod
    async def create_category(guild: nextcord.Guild, category_name: str, position: Optional[int] = None) -> str:
        """
        Công cụ tạo một Danh mục (Category) mới.
        Trả về chuỗi JSON chứa kết quả hoặc thông báo lỗi cho Agent đọc.
        """
        try:
            category = await guild.create   (name=category_name, position=position)
            result = {
                "status": "success",
                "action": "create_category",
                "category_name": category.name,
                "category_id": category.id
            }
            return json.dumps(result, ensure_ascii=False)
        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot không có quyền Administrator hoặc Manage Channels để tạo Category này."})
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Lỗi hệ thống ngoài dự kiến: {str(e)}"})

    @staticmethod
    async def create_channel(
        guild: nextcord.Guild, 
        channel_name: str, 
        channel_type: str, # 'text', 'voice', 'stage', 'forum'
        category_id: Optional[int] = None,
        topic: Optional[str] = None
    ) -> str:
        """
        Công cụ tạo một Kênh mới (Chữ hoặc Thoại) bên trong hoặc ngoài Danh mục.
        """
        try:
            # Xác định danh mục cha nếu có
            category = guild.get_channel(category_id) if category_id else None
            
            # Khởi tạo kênh dựa theo loại yêu cầu từ Agent
            if channel_type.lower() == "text":
                channel = await guild.create_text_channel(name=channel_name, category=category, topic=topic)
            elif channel_type.lower() == "voice":
                channel = await guild.create_voice_channel(name=channel_name, category=category)
            elif channel_type.lower() == "stage":
                channel = await guild.create_stage_channel(
                    name=channel_name, 
                    category=category,
                    topic=topic if topic is not None else "Welcome to the stage channel!"
                )
            elif channel_type.lower() == "forum":
                channel = await guild.create_forum_channel(
                    name=channel_name,
                    category=category,
                    topic=topic if topic is not None else "Welcome to the forum channel!"
                )
            else:
                return json.dumps({"status": "error", "message": f"Loại kênh '{channel_type}' không hợp lệ. Chỉ chấp nhận 'text', 'voice', 'stage', 'forum'."})

            result = {
                "status": "success",
                "action": "create_channel",
                "channel_name": channel.name,
                "channel_id": channel.id,
                "channel_type": channel_type,
                "parent_category_id": category_id
            }
            return json.dumps(result, ensure_ascii=False)
            
        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot bị từ chối quyền tạo kênh tại khu vực này."})
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Thất bại khi tạo kênh: {str(e)}"})

    @staticmethod
    async def modify_channel(
        guild: nextcord.Guild, 
        channel_id: int, 
        new_name: Optional[str] = None, 
        new_topic: Optional[str] = None,
        sync_permissions: bool = False
    ) -> str:
        """
        Công cụ chỉnh sửa thông tin Kênh hiện tại (Đổi tên, đổi chủ đề, đồng bộ quyền danh mục).
        """
        try:
            channel = guild.get_channel(channel_id)
            if not channel:
                return json.dumps({"status": "error", "message": "Không tìm thấy ID kênh yêu cầu trong Server."})

            kwargs = {}
            if new_name:
                kwargs['name'] = new_name
            if new_topic:
                # Kiểm tra xem đối tượng channel này trong thư viện nextcord có thuộc tính 'topic' hay không
                if hasattr(channel, 'topic'):
                    kwargs['topic'] = new_topic
                else:
                    return json.dumps({
                        "status": "error", 
                        "message": f"Kênh '{channel.name}' thuộc loại '{type(channel).__name__}', loại kênh này không hỗ trợ thuộc tính 'topic' (Ví dụ: Kênh thoại VoiceChannel)."
                    })
            if sync_permissions and channel.category:
                kwargs['overwrites'] = channel.category.overwrites

            await channel.edit(**kwargs)
            return json.dumps({"status": "success", "action": "modify_channel", "channel_id": channel_id, "updated_fields": list(kwargs.keys())})
            
        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot thiếu quyền chỉnh sửa kênh này."})
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Lỗi chỉnh sửa: {str(e)}"})

    @staticmethod
    async def delete_channel_or_category(guild: nextcord.Guild, target_id: int, reason: str = "Được yêu cầu bởi AI Agent") -> str:
        """
        Công cụ xóa bỏ một Kênh hoặc một Danh mục bất kỳ.
        """
        try:
            channel = guild.get_channel(target_id)
            if not channel:
                return json.dumps({"status": "error", "message": "Không tìm thấy kênh hoặc danh mục cần xóa."})

            target_name = channel.name
            await channel.delete(reason=reason)
            
            return json.dumps({
                "status": "success", 
                "action": "delete", 
                "target_name": target_name, 
                "target_id": target_id
            }, ensure_ascii=False)
            
        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot không có quyền xóa mục tiêu này."})
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Lỗi thực thi lệnh xóa: {str(e)}"})