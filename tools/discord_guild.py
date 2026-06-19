# tools/discord_guild.py hoặc bổ sung vào lớp Management
import json
import nextcord
import aiohttp
from typing import Optional, Dict, Any

class DiscordGuild:
    """
    Tập hợp các bộ công cụ (Tools) dành cho Agentic AI nhằm chỉnh sửa cấu hình cốt lõi
    của Máy chủ (Guild/Server) như Tên, Icon, Banner và các tính năng hệ thống.
    """

    @staticmethod
    async def modify_server_profile(guild: nextcord.Guild, **kwargs) -> str:
        """
        Công cụ chỉnh sửa thông tin hồ sơ của Server (Tên, Icon, Banner, Băng thông, Mức độ bảo mật).
        Hỗ trợ các tham số qua kwargs:
          - new_name: Đổi tên Server (str)
          - icon_url: Đường dẫn ảnh để đổi Avatar Server (str)
          - banner_url: Đường dẫn ảnh để đổi Ảnh nền Server (str)
          - verification_level: Mức độ xác minh bảo mật của Server (str: 'none', 'low', 'medium', 'high', 'highest')
          - enable_community: Bật hoặc tắt tính năng Cộng đồng (bool: True/False)
        """
        try:
            # Kiểm tra quyền: Chỉ có Chủ server hoặc người có quyền Administrator mới được sửa cấu hình Server
            if not guild.me.guild_permissions.manage_guild:
                return json.dumps({"status": "error", "message": "Bot thiếu quyền 'Manage Server' (Quản lý máy chủ) để thực hiện lệnh này."}, ensure_ascii=False)

            # Đổi tên tham số cho khớp với Nextcord API
            if 'new_name' in kwargs:
                kwargs['name'] = kwargs.pop('new_name')

            # Chuẩn hóa mức độ xác minh bảo mật (Verification Level) nếu Agent truyền vào
            if 'verification_level' in kwargs:
                v_level = kwargs['verification_level'].lower().strip()
                level_mapping = {
                    'none': nextcord.VerificationLevel.none,
                    'low': nextcord.VerificationLevel.low,
                    'medium': nextcord.VerificationLevel.medium,
                    'high': nextcord.VerificationLevel.high,
                    'highest': nextcord.VerificationLevel.highest
                }
                if v_level in level_mapping:
                    kwargs['verification_level'] = level_mapping[v_level]
                else:
                    kwargs.pop('verification_level') # Bỏ qua nếu Agent truyền bậy

            # Xử lý tải ảnh động bằng aiohttp nếu Agent truyền URL ảnh đại diện hoặc Banner
            async def download_image_bytes(url: str) -> Optional[bytes]:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url, timeout=10) as response:
                            if response.status == 200:
                                return await response.read()
                except:
                    return None
                return None

            if 'icon_url' in kwargs:
                img_bytes = await download_image_bytes(kwargs.pop('icon_url'))
                if img_bytes: kwargs['icon'] = img_bytes

            if 'banner_url' in kwargs:
                banner_bytes = await download_image_bytes(kwargs.pop('banner_url'))
                if banner_bytes: kwargs['banner'] = banner_bytes

            # TÍCH HỢP LOGIC NÂNG/HẠ CẤP CỘNG ĐỒNG (COMMUNITY)
            if 'enable_community' in kwargs:
                enable_community = kwargs.pop('enable_community')
                # Lấy danh sách các tính năng hiện tại của guild đưa vào mảng để tùy biến
                current_features = list(guild.features)

                if enable_community:
                    if "COMMUNITY" not in current_features:
                        current_features.append("COMMUNITY")
                        kwargs['features'] = current_features
                        
                        # Điều kiện bắt buộc của Discord: Phải gán kênh Quy định và kênh Cập nhật
                        # Nếu máy chủ chưa chỉ định sẵn, Bot lấy đại kênh văn bản đầu tiên của Server để lấp chỗ trống
                        fallback_channel = guild.text_channels[0] if guild.text_channels else None
                        if not fallback_channel:
                            return json.dumps({"status": "error", "message": "Thất bại: Server phải có ít nhất 1 kênh văn bản để làm kênh quy định khi bật Cộng đồng."}, ensure_ascii=False)
                        
                        kwargs['rules_channel'] = guild.rules_channel or fallback_channel
                        kwargs['public_updates_channel'] = guild.public_updates_channel or fallback_channel
                else:
                    if "COMMUNITY" in current_features:
                        current_features.remove("COMMUNITY")
                        kwargs['features'] = current_features

            # Lọc các tham số hợp lệ mà đối tượng Guild hỗ trợ sửa đổi trực tiếp
            valid_kwargs = {}
            for key, val in kwargs.items():
                if val is not None and hasattr(guild, key):
                    valid_kwargs[key] = val

            # Thực thi chỉnh sửa
            if valid_kwargs:
                await guild.edit(**valid_kwargs)

            # Chuẩn hóa lại tên hiển thị trong kết quả trả về cho đẹp
            updated_fields_log = list(valid_kwargs.keys())
            if 'features' in updated_fields_log:
                updated_fields_log.remove('features')
                updated_fields_log.append('community_status')

            return json.dumps({
                "status": "success",
                "action": "modify_server_profile",
                "guild_id": guild.id,
                "updated_fields": updated_fields_log
            }, ensure_ascii=False)

        except nextcord.Forbidden:
            return json.dumps({"status": "error", "message": "Bot bị từ chối quyền chỉnh sửa thông tin máy chủ."}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Thất bại khi sửa thông tin server: {str(e)}"}, ensure_ascii=False)

    @staticmethod
    async def get_server_info(guild: nextcord.Guild) -> str:
        """
        Công cụ quét và kết xuất toàn bộ thông tin trạng thái của Server (Tương ứng lệnh @server_info).
        Giúp Agent nắm được tổng quan tình hình Server trước khi đưa ra quyết định setup.
        """
        try:
            info = {
                "status": "success",
                "server_name": guild.name,
                "server_id": guild.id,
                "owner_id": guild.owner_id,
                "member_count": guild.member_count,
                "premium_tier_boost": guild.premium_tier, # Cấp độ Boost của server
                "premium_subscription_count": guild.premium_subscription_count, # Số lượng lượt Boost
                "verification_level": str(guild.verification_level),
                "total_channels": len(guild.channels),
                "total_roles": len(guild.roles),
                "icon_url": guild.icon.url if guild.icon else None,
                "banner_url": guild.banner.url if guild.banner else None,
                "features": list(guild.features)
            }
            return json.dumps(info, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"status": "error", "message": f"Không thể lấy thông tin server: {str(e)}"}, ensure_ascii=False)