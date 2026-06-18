import nextcord
from nextcord.ext import commands
import os
from dotenv import load_dotenv

#=== THƯ VIỆN BỔ SUNG ===
import json
import io
import asyncio
import aiohttp 
import zipfile
import time
from datetime import datetime

load_dotenv()

intents = nextcord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True 

bot = commands.Bot(command_prefix="!", intents=intents)

# ----- BIẾN LƯU CẤU HÌNH XÁC MINH (Dành cho lệnh 38) -----
verify_config = {}  # {guild_id: {"message_id": ..., "channel_id": ..., "role_id": ..., "emoji": ...}}
VERIFY_DATA_FILE = "verify_data.json"

def load_verify_config():
    global verify_config
    if os.path.exists(VERIFY_DATA_FILE):
        with open(VERIFY_DATA_FILE, "r", encoding="utf-8") as f:
            verify_config = json.load(f)

def save_verify_config():
    with open(VERIFY_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(verify_config, f, ensure_ascii=False, indent=4)

auto_delete_channels = {}

@bot.event
async def on_ready():
    print(f"🤖 Bot Quản Trị Kênh Nâng Cấp Đã Sẵn Sàng: {bot.user}")

@bot.command(name="bot_info")
async def bot_info(ctx):
    # Lấy danh sách tất cả các guild (server) mà bot đang tham gia
    guilds_list = bot.guilds
    total_servers = len(guilds_list)
    
    # Tạo chuỗi danh sách tên các server (giới hạn hiển thị nếu quá nhiều)
    server_names = ", ".join([guild.name for guild in guilds_list])
    if not server_names:
        server_names = "Bot chưa tham gia server nào."

    # Tạo nội dung phản hồi
    msg = (
        f"📊 **Thông tin Bot:**\n"
        f"🔹 **Số lượng server đã tham gia:** {total_servers}/10\n"
        f"📝 **Danh sách server:** {server_names}\n"
    )
    
    # Cảnh báo nếu bot đã chạm hoặc vượt giới hạn tạo server
    if total_servers >= 10:
        msg += "⚠️ **Lưu ý:** Bot đã tham gia từ 10 server trở lên, hàm `create_guild` sẽ không hoạt động được nữa!"
    else:
        msg += "✅ Bot vẫn đủ điều kiện để tự tạo server mới."

    await ctx.send(msg)

@bot.command(name="create_server")
async def create_server(ctx, *, server_name: str): # Dấu * giúp nhận toàn bộ tên server có khoảng trắng (Ví dụ: !create_server My New Server)
    try:
        # SỬA TẠI ĐÂY: Gọi hàm từ 'bot' chứ không phải 'guild'
        new_guild = await bot.create_guild(name=server_name)
        
        # Lấy kênh chữ đầu tiên của server mới để tạo link mời
        default_channel = new_guild.text_channels[0]
        invite = await default_channel.create_invite(max_age=3600) # Link hết hạn sau 1 tiếng
        
        await ctx.send(
            f"🎉 Đã tạo thành công server **{new_guild.name}**!\n"
            f"🔗 Tham gia ngay tại đây: {invite.url}"
        )
        
    except nextcord.HTTPException as e:
        # Lỗi xảy ra khi Bot đã ở trong > 10 server hoặc lỗi API từ Discord
        await ctx.send(
            f"❌ Không thể tạo server. Lý do: Bot của bạn có thể đã tham gia vượt quá giới hạn 10 server của Discord."
        )

# --- 1. LỆNH TẠO KÊNH NÂNG CẤP (Hỗ trợ Thể loại & Ẩn/Hiện) ---
# Cú pháp: !tao_kenh [loai] [che_do] [Tên Kênh]
# Giá trị mặc định: loai="text", che_do="hien"
@bot.command(name="tao_kenh")
@commands.has_permissions(manage_channels=True)
async def tao_kenh(ctx, loai: str = "text", che_do: str = "hien", *, ten_kenh: str):
    try:
        guild = ctx.guild
        loai_kenh = loai.lower()
        che_do_xem = che_do.lower()

        # --- BƯỚC 1: TẠO KÊNH TRỐNG (MẶC ĐỊNH) ---
        kenh_moi = None
        
        if loai_kenh in ["text", "txt", "văn-bản"]:
            kenh_moi = await guild.create_text_channel(name=ten_kenh)
        elif loai_kenh in ["voice", "vc", "thoại"]:
            kenh_moi = await guild.create_voice_channel(name=ten_kenh)
        elif loai_kenh in ["stage", "sân-khấu"]:
            kenh_moi = await guild.create_stage_channel(
                name=ten_kenh, 
                topic="Chào mừng bạn đến với sân khấu!"
            )
        elif loai_kenh in ["forum", "diễn-đàn"]:
            kenh_moi = await guild.create_forum_channel(
                name=ten_kenh, 
                topic="Chào mừng bạn đến với diễn đàn!"
            )
        else:
            await ctx.send("⚠️ Thể loại kênh không hợp lệ (`text`/`voice`/`forum`/`stage`)!")
            return

        # --- BƯỚC 2: SETUP QUYỀN HẠN (ẨN/HIỆN) SAU KHI KÊNH ĐÃ KHỞI TẠO ---
        if kenh_moi:
            if che_do_xem in ["an", "ẩn", "private"]:
                # Khóa quyền xem của vai trò mặc định @everyone
                await kenh_moi.set_permissions(guild.default_role, view_channel=False)
            elif che_do_xem in ["hien", "hiện", "public"]:
                # Mở quyền xem của vai trò mặc định @everyone
                await kenh_moi.set_permissions(guild.default_role, view_channel=True)
            else:
                # Trường hợp người dùng gõ nhầm cú pháp
                await ctx.send(f"⚠️ Chế độ xem `{che_do}` không hợp lệ. Kênh sẽ giữ ở mặc định công khai!")

            await ctx.send(f"✨ Đã tạo thành công kênh **{loai_kenh}** ({che_do_xem}): {kenh_moi.mention}")

    except nextcord.Forbidden:
        await ctx.send("❌ Bot không có đủ quyền `Manage Channels` để thực hiện thao tác này.")
    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi khi tạo kênh: {e}")


# --- 2. LỆNH SỬA TÊN KÊNH (Giữ nguyên) ---
@bot.command(name="sua_kenh")
@commands.has_permissions(manage_channels=True)
async def sua_kenh(ctx, channel: nextcord.abc.GuildChannel, *, ten_moi: str):
    try:
        ten_cu = channel.name
        await channel.edit(name=ten_moi)
        await ctx.send(f"✅ Đã đổi tên kênh từ **{ten_cu}** thành **{ten_moi}**!")
    except nextcord.Forbidden:
        await ctx.send("❌ Bot không có đủ quyền `Manage Channels` để sửa kênh này.")
    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi: {e}")


# --- 3. LỆNH XÓA KÊNH (Giữ nguyên) ---
@bot.command(name="xoa_kenh")
@commands.has_permissions(manage_channels=True)
async def xoa_kenh(ctx, channel: nextcord.abc.GuildChannel):
    try:
        ten_kenh = channel.name
        if channel.id == ctx.channel.id:
            try: await ctx.author.send(f"🗑️ Bạn đã xóa thành công kênh **#{ten_kenh}** tại server **{ctx.guild.name}**.")
            except nextcord.Forbidden: pass
            await channel.delete()
        else:
            await channel.delete()
            await ctx.send(f"🗑️ Đã xóa thành công kênh: **{ten_kenh}**")
    except nextcord.Forbidden:
        await ctx.send("❌ Bot không có đủ quyền `Manage Channels` để xóa kênh này.")
    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi: {e}")


# --- 4. LỆNH DI CHUYỂN KÊNH VÀO/RA KHỎI DANH MỤC (Giữ nguyên) ---
@bot.command(name="di_chuyen")
@commands.has_permissions(manage_channels=True)
async def di_chuyen(ctx, channel: nextcord.abc.GuildChannel, *, danh_muc_input: str):
    try:
        guild = ctx.guild
        if danh_muc_input.lower() == "none":
            await channel.edit(category=None)
            await ctx.send(f"🔓 Đã đưa kênh {channel.mention} ra khỏi danh mục!")
            return

        target_category = None
        if danh_muc_input.isdigit():
            target_category = nextcord.utils.get(guild.categories, id=int(danh_muc_input))
        if not target_category:
            target_category = nextcord.utils.get(guild.categories, name=danh_muc_input)
            if not target_category:
                target_category = next((cat for cat in guild.categories if danh_muc_input.lower() in cat.name.lower()), None)

        if not target_category:
            await ctx.send(f"❌ Không tìm thấy danh mục: `{danh_muc_input}`")
            return

        await channel.edit(category=target_category)
        await ctx.send(f"📁 Đã di chuyển kênh {channel.mention} vào danh mục **{target_category.name}**!")
    except nextcord.Forbidden:
        await ctx.send("❌ Bot không có đủ quyền `Manage Channels` để thực hiện.")
    except Exception as e:
        await ctx.send(f"❌ Lỗi: {e}")


# --- 5. LỆNH SẮP XẾP THỨ TỰ KÊNH TRONG DANH MỤC (Mới) ---
# Cú pháp: !sap_xep [Tên/ID Danh Mục] [#kênh1] [#kênh2] [#kênh3]...
# Ví dụ:   !sap_xep KHU-CHAT #kênh-thông-báo #kênh-luật #phòng-tán-dẫu
@bot.command(name="sap_xep")
@commands.has_permissions(manage_channels=True)
async def sap_xep(ctx, danh_muc_input: str, *channels: nextcord.abc.GuildChannel):
    try:
        guild = ctx.guild

        # 1. Tìm danh mục đích
        target_category = None
        if danh_muc_input.isdigit():
            target_category = nextcord.utils.get(guild.categories, id=int(danh_muc_input))
        if not target_category:
            target_category = nextcord.utils.get(guild.categories, name=danh_muc_input)
            if not target_category:
                target_category = next((cat for cat in guild.categories if danh_muc_input.lower() in cat.name.lower()), None)

        if not target_category:
            await ctx.send(f"❌ Không tìm thấy danh mục: `{danh_muc_input}`")
            return

        if not channels:
            await ctx.send("⚠️ Hãy tag danh sách các kênh cần sắp xếp theo thứ tự mong muốn!")
            return

        # 2. Xây dựng dictionary cấu hình vị trí mới (Bắt đầu từ index 0)
        # Đồng thời đảm bảo các kênh này thuộc về danh mục được chỉ định
        payload = {}
        thong_bao_list = []
        
        for index, channel in enumerate(channels):
            # Nếu kênh chưa nằm trong danh mục, bot sẽ tự động gom nó vào danh mục đó luôn
            payload[channel] = {
                "position": index,
                "category_id": target_category.id
            }
            thong_bao_list.append(f"{index + 1}. {channel.name}")

        # 3. Gửi lệnh chỉnh sửa hàng loạt (Bulk edit positions) lên Discord API
        await guild.edit_channel_positions(positions=payload)
        
        danh_sach_chuoi = "\n".join(thong_bao_list)
        await ctx.send(f"📊 Đã sắp xếp lại thứ tự kênh trong danh mục **{target_category.name}**:\n```text\n{danh_sach_chuoi}\n```")

    except nextcord.Forbidden:
        await ctx.send("❌ Bot thiếu quyền `Manage Channels` để thay đổi thứ tự kênh.")
    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi khi sắp xếp: {e}")

# --- 6. LỆNH KÍCH HOẠT TÍNH NĂNG CỘNG ĐỒNG (ĐÃ SỬA LỖI) ---
# Cú pháp: !bat_cong_dong
@bot.command(name="bat_cong_dong")
@commands.has_permissions(administrator=True)
async def bat_cong_dong(ctx):
    try:
        guild = ctx.guild
        
        if "COMMUNITY" in guild.features:
            await ctx.send("📢 Server này đã được kích hoạt tính năng Cộng đồng từ trước rồi!")
            return

        await ctx.send("⏳ Đang thiết lập cấu hình nâng cấp Cộng đồng...")

        # 1. Tìm hoặc tạo kênh Quy định
        rules_channel = nextcord.utils.get(guild.text_channels, name="quy-định")
        if not rules_channel:
            rules_channel = await guild.create_text_channel(name="quy-định")
            await rules_channel.send("📜 **QUY ĐỊNH SERVER**\n1. Tôn trọng lẫn nhau.\n2. Không spam.")

        # 2. Tìm hoặc tạo kênh Cập nhật hệ thống
        updates_channel = nextcord.utils.get(guild.text_channels, name="thông-báo-admin")
        if not updates_channel:
            updates_channel = await guild.create_text_channel(name="thông-báo-admin")
            await updates_channel.send("🛠️ Kênh nhận thông báo cập nhật hệ thống dành cho Ban Quản Trị.")

        # 3. Sử dụng tham số nâng cấp cộng đồng chuẩn của nextcord
        await guild.edit(
            community=True, # <--- Bật tính năng cộng đồng bằng cách này
            rules_channel=rules_channel,
            public_updates_channel=updates_channel,
            verification_level=nextcord.VerificationLevel.medium,
            explicit_content_filter=nextcord.ContentFilter.all_members
        )

        await ctx.send(f"✅ **Kích hoạt thành công!** Server đã được nâng cấp lên Server Cộng Đồng.\n• Kênh nội quy: {rules_channel.mention}\n• Kênh cập nhật Admin: {updates_channel.mention}")

    except nextcord.Forbidden:
        await ctx.send("❌ Bot thiếu quyền `Administrator` để thay đổi cấu hình hệ thống Server.")
    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi khi kích hoạt: {e}")


# --- 7. LỆNH HỦY TÍNH NĂNG CỘNG ĐỒNG (ĐÃ SỬA LỖI) ---
# Cú pháp: !tat_cong_dong
@bot.command(name="tat_cong_dong")
@commands.has_permissions(administrator=True)
async def tat_cong_dong(ctx):
    try:
        guild = ctx.guild

        if "COMMUNITY" not in guild.features:
            await ctx.send("⚠️ Server này hiện tại vốn không ở chế độ Cộng đồng.")
            return

        await ctx.send("⏳ Đang hủy cấu hình Cộng đồng, đưa Server về chế độ thường...")

        # Tắt cộng đồng bằng cách truyền community=False
        # Discord sẽ tự động ngắt kết nối với các kênh quy định/cập nhật cũ
        await guild.edit(
            community=False, # <--- Tắt tính năng cộng đồng bằng cách này
            rules_channel=None,
            public_updates_channel=None
        )

        await ctx.send("🔓 Đã **Hủy kích hoạt** tính năng Cộng đồng thành công! Server của bạn đã trở lại trạng thái Server cá nhân thông thường.")

    except nextcord.Forbidden:
        await ctx.send("❌ Bot thiếu quyền cấu hình Server để tắt tính năng này.")
    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi khi tắt Cộng đồng: {e}")

# --- 8. LỆNH TẠO VAI TRÒ MỚI ---
# Cú pháp: !tao_role [Màu_Hex] [Tên Vai Trò]
# Ví dụ:   !tao_role #ff0000 Vip Member  (Tạo role màu đỏ)
#          !tao_role none Thành Viên Mới (Tạo role không màu)
@bot.command(name="tao_role")
@commands.has_permissions(manage_roles=True)
async def tao_role(ctx, mau_hex: str="#00ff00", *, ten_role: str):
    try:
        guild = ctx.guild
        
        # Xử lý màu sắc cho Role
        if mau_hex.lower() == "none":
            color = nextcord.Color.default()
        else:
            try:
                # Chuyển chuỗi Hex (#ffffff) thành đối từ Color của nextcord
                mau_hex = mau_hex.strip()
                if not mau_hex.startswith("#"):
                    mau_hex = f"#{mau_hex}"
                color = nextcord.Color.from_rgb(*tuple(int(mau_hex.lstrip('#')[i:i+2], 16) for i in (0, 2, 4)))
            except ValueError:
                await ctx.send("⚠️ Mã màu Hex không hợp lệ! Ví dụ đúng: `#ff0000` (Đỏ) hoặc nhập `none` để dùng màu mặc định.")
                return

        # Tiến hành tạo Role mới
        role_moi = await guild.create_role(name=ten_role, color=color, reason=f"Được tạo bởi {ctx.author}")
        await ctx.send(f"✨ Đã tạo thành công vai trò mới: {role_moi.mention} với mã màu `{mau_hex}`!")

    except nextcord.Forbidden:
        await ctx.send("❌ Bot không có đủ quyền `Manage Roles` hoặc vị trí vai trò của Bot thấp hơn vai trò cần tạo.")
    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi khi tạo vai trò: {e}")


# --- 9. LỆNH SỬA VAI TRÒ ---
# Cú pháp: !sua_role [@Tag_Role hoặc ID_Role] [Màu_Hex_Mới] [Tên Mới]
# Ví dụ:   !sua_role @Vip Member #00ff00 Super VIP
@bot.command(name="sua_role")
@commands.has_permissions(manage_roles=True)
async def sua_role(ctx, role: nextcord.Role, mau_hex_moi: str, *, ten_moi: str):
    try:
        # Xử lý màu sắc mới
        if mau_hex_moi.lower() == "none":
            color = nextcord.Color.default()
        else:
            try:
                if not mau_hex_moi.startswith("#"):
                    mau_hex_moi = f"#{mau_hex_moi}"
                color = nextcord.Color.from_rgb(*tuple(int(mau_hex_moi.lstrip('#')[i:i+2], 16) for i in (0, 2, 4)))
            except ValueError:
                await ctx.send("⚠️ Mã màu Hex mới không hợp lệ! Ví dụ đúng: `#00ff00`.")
                return

        # Tiến hành cập nhật Role
        ten_cu = role.name
        await role.edit(name=ten_moi, color=color, reason=f"Được sửa bởi {ctx.author}")
        await ctx.send(f"✅ Đã cập nhật vai trò từ **{ten_cu}** thành {role.mention} thành công!")

    except nextcord.Forbidden:
        await ctx.send("❌ Bot không thể sửa vai trò này. Hãy chắc chắn rằng vai trò của Bot nằm TRÊN vai trò bạn muốn sửa trong cài đặt server!")
    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi khi sửa: {e}")


# --- 10. LỆNH XÓA VAI TRÒ ---
# Cú pháp: !xoa_role [@Tag_Role hoặc ID_Role]
# Ví dụ:   !xoa_role @Super VIP
@bot.command(name="xoa_role")
@commands.has_permissions(manage_roles=True)
async def xoa_role(ctx, role: nextcord.Role):
    try:
        ten_role = role.name
        
        # Tiến hành xóa Role
        await role.delete(reason=f"Được xóa bởi {ctx.author}")
        await ctx.send(f"🗑️ Đã xóa thành công vai trò: **{ten_role}** khỏi server.")

    except nextcord.Forbidden:
        await ctx.send("❌ Bot không có đủ quyền xóa hoặc vai trò này nằm cao hơn thứ tự vai trò của Bot.")
    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi khi xóa: {e}")

# --- 11. LỆNH GÁN VAI TRÒ CHO THÀNH VIÊN ---
# Cú pháp: !gan_role [@Tag_Thành_Viên hoặc ID] [@Tag_Role hoặc ID]
# Ví dụ:   !gan_role @NguyenVanA @Người Lập Trình
@bot.command(name="gan_role")
@commands.has_permissions(manage_roles=True)
async def gan_role(ctx, member: nextcord.Member, role: nextcord.Role):
    try:
        # Kiểm tra xem thành viên đã có vai trò này chưa
        if role in member.roles:
            await ctx.send(f"⚠️ Thành viên {member.mention} đã sở hữu vai trò {role.mention} từ trước rồi!")
            return

        # Tiến hành gán vai trò
        await member.add_roles(role, reason=f"Được gán bởi {ctx.author}")
        await ctx.send(f"✅ Đã gán thành công vai trò {role.mention} cho {member.mention}!")

    except nextcord.Forbidden:
        await ctx.send("❌ Bot không thể gán vai trò này! Hãy đảm bảo vai trò của Bot nằm CAO HƠN vai trò bạn muốn gán trong Cài đặt Server.")
    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi khi gán vai trò: {e}")


# --- 12. LỆNH GỠ VAI TRÒ KHỎI THÀNH VIÊN ---
# Cú pháp: !go_role [@Tag_Thành_Viên hoặc ID] [@Tag_Role hoặc ID]
# Ví dụ:   !go_role @NguyenVanA @Người Lập Trình
@bot.command(name="go_role")
@commands.has_permissions(manage_roles=True)
async def go_role(ctx, member: nextcord.Member, role: nextcord.Role):
    try:
        # Kiểm tra xem thành viên có vai trò này để gỡ không
        if role not in member.roles:
            await ctx.send(f"⚠️ Thành viên {member.mention} hiện không có vai trò {role.mention} để gỡ!")
            return

        # Tiến hành gỡ vai trò
        await member.remove_roles(role, reason=f"Được gỡ bởi {ctx.author}")
        await ctx.send(f"🗑️ Đã gỡ thành công vai trò {role.mention} khỏi {member.mention}!")

    except nextcord.Forbidden:
        await ctx.send("❌ Bot không thể gỡ vai trò này! Hãy đảm bảo vai trò của Bot nằm CAO HƠN vai trò bạn muốn gỡ trong Cài đặt Server.")
    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi khi gỡ vai trò: {e}")

import datetime

# --- 13. LỆNH ĐUỔI THÀNH VIÊN (KICK) ---
# Cú pháp: !kick @Tên_Thành_Viên [Lý do]
@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: nextcord.Member, *, ly_do: str = "Không có lý do cụ thể."):
    try:
        await member.kick(reason=f"{ly_do} | Người thực hiện: {ctx.author}")
        await ctx.send(f"👢 Đã đuổi thành viên **{member.name}** ra khỏi server. Lý do: `{ly_do}`")
    except nextcord.Forbidden:
        await ctx.send("❌ Bot không đủ quyền hạn để đuổi người này (có thể vai trò của họ cao hơn Bot).")

# --- 14. LỆNH CẤM THÀNH VIÊN (BAN) ---
# Cú pháp: !ban @Tên_Thành_Viên [Lý do]
@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: nextcord.Member, *, ly_do: str = "Không có lý do cụ thể."):
    try:
        await member.ban(reason=f"{ly_do} | Người thực hiện: {ctx.author}", delete_message_seconds=604800) # Xóa tin nhắn trong 7 ngày qua
        await ctx.send(f"🔨 Đã cấm **{member.name}** truy cập server vĩnh viễn. Lý do: `{ly_do}`")
    except nextcord.Forbidden:
        await ctx.send("❌ Bot không đủ quyền hạn để cấm thành viên này.")

# --- 15. LỆNH CẤM TẠM THỜI / CÁCH LY (TIMEOUT / MUTE) ---
# Cú pháp: !timeout @Tên_Thành_Viên [Số phút] [Lý do]
# Ví dụ:   !timeout @NguyenVanA 10 Spam chat
@bot.command(name="timeout")
@commands.has_permissions(moderate_members=True)
async def timeout(ctx, member: nextcord.Member, phut: int, *, ly_do: str = "Không có lý do cụ thể."):
    try:
        duration = datetime.timedelta(minutes=phut)
        await member.timeout(duration, reason=f"{ly_do} | Người thực hiện: {ctx.author}")
        await ctx.send(f"🤫 Đã cách ly (Timeout) **{member.name}** trong vòng **{phut}** phút. Lý do: `{ly_do}`")
    except nextcord.Forbidden:
        await ctx.send("❌ Bot không đủ quyền hạn để timeout thành viên này.")

# --- 16. LỆNH XÓA TIN NHẮN HÀNG LOẠT (PURGE) ---
# Cú pháp: !xoa_tin [Số lượng tin nhắn từ 1-100]
# Ví dụ:   !xoa_tin 50
@bot.command(name="xoa_tin")
@commands.has_permissions(manage_messages=True)
async def xoa_tin(ctx, so_luong: int):
    if so_luong < 1 or so_luong > 100:
        await ctx.send("⚠️ Bạn chỉ có thể xóa từ 1 đến 100 tin nhắn trong một lần.")
        return
    
    try:
        # Cộng thêm 1 để xóa luôn chính tin nhắn lệnh gõ của người dùng
        deleted = await ctx.channel.purge(limit=so_luong + 1)
        # Gửi thông báo tự động xóa sau 5 giây để tránh làm rác kênh
        await ctx.send(f"🧹 Đã dọn dẹp thành công **{len(deleted) - 1}** tin nhắn!", delete_after=5)
    except Exception as e:
        await ctx.send(f"❌ Không thể xóa tin nhắn: {e}")

# --- 17. LỆNH XEM THÔNG TIN SERVER (SERVER INFO) ---
# Cú pháp: !server_info
@bot.command(name="server_info")
async def server_info(ctx):
    try:
        guild = ctx.guild
        
        # Sửa lỗi: Lấy ID chủ server rồi nhờ Bot fetch (tải) thông tin user về
        chu_server_id = guild.owner_id
        try:
            chu_server = await bot.fetch_user(chu_server_id)
            chu_server_mention = chu_server.mention
        except Exception:
            chu_server_mention = f"<@{chu_server_id}>" # Nếu lỗi fetch thì tự render dạng tag ID
        
        # Đếm số lượng thành viên thực tế và số bot
        total_members = guild.member_count
        bots = sum(1 for member in guild.members if member.bot)
        humans = total_members - bots
        
        # Định dạng ngày tạo server ngày/tháng/năm
        ngay_tao = guild.created_at.strftime("%d/%m/%Y")

        # Tạo giao diện báo cáo dạng văn bản sạch
        info = (
            f"📊 **THÔNG TIN SERVER: {guild.name}**\n"
            f"• **Chủ server:** {chu_server_mention}\n"
            f"• **Ngày khởi tạo:** {ngay_tao}\n"
            f"• **Tổng số thành viên:** {total_members} (Người chơi: {humans} | Bot: {bots})\n"
            f"• **Số lượng kênh:** {len(guild.channels)} channels\n"
            f"• **Số lượng vai trò (Roles):** {len(guild.roles)} roles\n"
            f"• **Cấp độ Boost:** Level {guild.premium_tier} ({guild.premium_subscription_count} boosts)"
        )
        await ctx.send(info)
        
    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi khi lấy thông tin server: {e}")

# --- 18. LỆNH ĐỔI BIỆT DANH THÀNH VIÊN ---
# Cú pháp: !doi_ten @Tên_Thành_Viên [Tên mới]
# Ví dụ:   !doi_ten @NguyenVanA Học Viên Khá
@bot.command(name="doi_ten")
@commands.has_permissions(manage_nicknames=True)
async def doi_ten(ctx, member: nextcord.Member, *, ten_moi: str):
    try:
        await member.edit(nick=ten_moi, reason=f"Đổi bởi {ctx.author}")
        await ctx.send(f"✏️ Đã đổi biệt danh của thành viên thành: **{ten_moi}**")
    except nextcord.Forbidden:
        await ctx.send("❌ Bot không đủ quyền chỉnh sửa tên của người này.")

# --- 19. LỆNH XÓA BIỆT DANH THÀNH VIÊN (RESET TÊN GỐC) ---
# Cú pháp: !xoa_ten [@Tag_Thành_Viên hoặc ID]
# Ví dụ:   !xoa_ten @NguyenVanA
@bot.command(name="xoa_ten")
@commands.has_permissions(manage_nicknames=True) # Yêu cầu quyền quản lý biệt danh
async def xoa_ten(ctx, member: nextcord.Member):
    try:
        # Nếu thành viên hiện tại vốn không có biệt danh (đang dùng tên gốc)
        if member.nick is None:
            await ctx.send(f"⚠️ Thành viên **{member.name}** hiện đang sử dụng tên gốc, không có biệt danh để xóa!")
            return

        ten_cu = member.display_name
        
        # Gán thuộc tính nick = None để reset về tên mặc định của Discord
        await member.edit(nick=None, reason=f"Bị xóa biệt danh bởi {ctx.author}")
        
        await ctx.send(f"♻️ Đã gỡ bỏ biệt danh **{ten_cu}**. Thành viên đã được reset về tên gốc: **{member.name}**")

    except nextcord.Forbidden:
        await ctx.send("❌ Bot không đủ quyền hạn để xóa biệt danh của người này (vị trí vai trò của họ cao hơn Bot).")
    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi khi xóa biệt danh: {e}")

# --- 20. LỆNH XEM THÔNG TIN KÊNH (CHANNEL INFO) ---
# Cú pháp: !kenh_info [#tên-kênh hoặc bỏ trống]
# Ví dụ:   !kenh_info #chat-chung  hoặc chỉ gõ  !kenh_info
@bot.command(name="kenh_info")
async def kenh_info(ctx, channel: nextcord.abc.GuildChannel = None):
    try:
        # Nếu người dùng không truyền kênh nào, tự động lấy kênh hiện tại
        if channel is None:
            channel = ctx.channel

        ngay_tao = channel.created_at.strftime("%d/%m/%Y lúc %H:%M")
        
        # Phân loại kiểu kênh để hiển thị trực quan
        loai_kenh = "Văn bản (Text Channel)"
        if isinstance(channel, nextcord.VoiceChannel):
            loai_kenh = "Thoại (Voice Channel)"
        elif isinstance(channel, nextcord.StageChannel):
            loai_kenh = "Sân khấu (Stage Channel)"
        elif isinstance(channel, nextcord.ForumChannel):
            loai_kenh = "Diễn đàn (Forum Channel)"
        elif isinstance(channel, nextcord.CategoryChannel):
            loai_kenh = "Danh mục (Category)"

        # Lấy thông tin danh mục cha (nếu có)
        danh_muc = channel.category.name if channel.category else "Không nằm trong danh mục"

        info = (
            f"📁 **THÔNG TIN KÊNH: {channel.name}**\n"
            f"• **ID Kênh:** `{channel.id}`\n"
            f"• **Loại kênh:** {loai_kenh}\n"
            f"• **Vị trí hiển thị:** Thứ {channel.position + 1}\n"
            f"• **Thuộc danh mục:** **{danh_muc}**\n"
            f"• **Ngày khởi tạo:** {ngay_tao}\n"
        )
        
        # Bổ sung thông tin riêng nếu đó là kênh văn bản (Chủ đề kênh)
        if isinstance(channel, nextcord.TextChannel) and channel.topic:
            info += f"• **Chủ đề kênh (Topic):** {channel.topic}\n"

        await ctx.send(info)

    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi khi lấy thông tin kênh: {e}")


# --- 21. LỆNH XEM THÔNG TIN USER (USER INFO / WHOIS) ---
# Cú pháp: !user_info [@Tag_Thành_Viên hoặc bỏ trống]
# Ví dụ:   !user_info @NguyenVanA  hoặc chỉ gõ  !user_info
@bot.command(name="user_info")
async def user_info(ctx, member: nextcord.Member = None):
    try:
        # Nếu không tag ai, tự động lấy chính người gõ lệnh
        if member is None:
            member = ctx.author

        # Lấy danh sách các vai trò (bỏ qua role @everyone mặc định)
        roles = [role.mention for role in member.roles if role != ctx.guild.default_role]
        danh_sach_role = ", ".join(roles) if roles else "Không có vai trò nào"

        # Định dạng thời gian
        ngay_tao_tk = member.created_at.strftime("%d/%m/%Y")
        ngay_vao_server = member.joined_at.strftime("%d/%m/%Y") if member.joined_at else "Không rõ"

        # Kiểm tra xem có phải tài khoản Bot không
        la_bot = "Phải (Robot 🤖)" if member.bot else "Không (Người chơi 👤)"

        info = (
            f"👤 **THÔNG TIN THÀNH VIÊN: {member.name}**\n"
            f"• **Tên hiển thị:** {member.display_name}\n"
            f"• **ID Tài khoản:** `{member.id}`\n"
            f"• **Là tài khoản Bot?:** {la_bot}\n"
            f"• **Ngày tạo tài khoản Discord:** {ngay_tao_tk}\n"
            f"• **Ngày tham gia Server:** {ngay_vao_server}\n"
            f"• **Vai trò sở hữu:** {danh_sach_role}\n"
        )
        
        await ctx.send(info)

    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi khi lấy thông tin thành viên: {e}")

import urllib.parse  # Thêm dòng này ở đầu file code của bạn nếu chưa có

# --- 22. LỆNH TẠO SERVER THEO TEMPLATE CHỈ ĐỊNH (SỬA LỖI LINK ĐỘNG) ---
# Cú pháp: !tao_server [loai_mau] [Tên Server]
# Ví dụ:   !tao_server gaming Server Chiến Game Đỉnh
# @bot.command(name="tao_server")
# async def tao_server(ctx, loai_mau: str = "gaming", *, ten_server: str):
#     if not ctx.author.guild_permissions.administrator:
#         await ctx.send("❌ Bạn phải là Quản trị viên (Administrator) mới được dùng lệnh này!")
#         return

#     # Sử dụng chính xác mã template Gaming của bạn
#     ma_template_gaming = "6cfHZFDdJPjY"
    
#     # Chuẩn hóa loại mẫu người dùng gõ
#     loai_nhap = loai_mau.lower()

#     # Kiểm tra xem người dùng muốn tạo mẫu gì
#     if loai_nhap in ["gaming", "game", "trò-chơi"]:
#         link_chuan = f"https://discord.new/{ma_template_gaming}"
        
#         giao_dien = (
#             f"👑 **THIẾT LẬP MÁY CHỦ GAMING ĐÃ SẴN SÀNG**\n"
#             f"Bot đã cấu hình xong mẫu thiết kế theo yêu cầu của bạn:\n\n"
#             f"👉 **[BẤM VÀO ĐÂY ĐỂ KHỞI TẠO MÁY CHỦ]({link_chuan})**\n\n"
#             f"📝 **Hướng dẫn 2 bước thực hiện khi cửa sổ hiện ra:**\n"
#             f"1️⃣ Tại ô **TÊN MÁY CHỦ (SERVER NAME)**: Bạn hãy copy và dán chính xác tên này vào: `{ten_server}`\n"
#             f"2️⃣ Nhấn nút **Tạo (Create)** ở góc dưới để hoàn tất và nhận ngay quyền Chủ Server!"
#         )
#     else:
#         # Nếu người dùng gõ loại khác (ví dụ: học-tập, clb...) mà bạn chưa có mã
#         giao_dien = (
#             f"⚠️ Hiện tại Bot mới chỉ hỗ trợ mẫu `gaming` thông qua mã cá nhân của bạn.\n"
#             f"Mặc định Bot sẽ cung cấp mẫu Gaming cho tên server: **{ten_server}**\n\n"
#             f"👉 **[Bấm vào đây để tạo mẫu Gaming của bạn](https://discord.new/{ma_template_gaming})**\n"
#             f"*(Đừng quên đổi tên thành `{ten_server}` trước khi bấm nút Tạo nhé!)*"
#         )

#     await ctx.send(giao_dien)


# --- 23. LỆNH SAO LƯU CẤU HÌNH SERVER ---
@bot.command(name="sao_luu")
@commands.has_permissions(administrator=True)
async def backup_config(ctx):
    """
    Xuất file JSON chứa cấu hình server (vai trò, danh mục, kênh, phân quyền).
    File sẽ được gửi vào kênh hiện tại.
    """
    try:
        guild = ctx.guild
        data = {
            "guild_name": guild.name,
            "roles": [],
            "categories": [],
            "channels": []
        }

        # Lưu vai trò (trừ @everyone)
        for role in guild.roles:
            if role.is_default():
                continue
            data["roles"].append({
                "id": role.id,
                "name": role.name,
                "color": role.color.value,
                "hoist": role.hoist,
                "mentionable": role.mentionable,
                "permissions": role.permissions.value
            })

        # Lưu danh mục và kênh
        for category in guild.categories:
            cat_data = {
                "id": category.id,
                "name": category.name,
                "position": category.position,
                "overwrites": _serialize_overwrites(category.overwrites)
            }
            data["categories"].append(cat_data)
            for channel in category.channels:
                data["channels"].append(_serialize_channel(channel, category_id=category.id))

        # Kênh không thuộc danh mục nào
        for channel in guild.channels:
            if channel.category is None and not isinstance(channel, nextcord.CategoryChannel):
                data["channels"].append(_serialize_channel(channel, category_id=None))

        json_str = json.dumps(data, indent=2, ensure_ascii=False)
        file = io.BytesIO(json_str.encode('utf-8'))
        await ctx.send(
            content="📦 **File sao lưu cấu hình server**",
            file=nextcord.File(file, filename=f"backup_{guild.id}.json")
        )
    except nextcord.Forbidden:
        await ctx.send("❌ Bot không có đủ quyền để đọc toàn bộ kênh/vai trò.")
    except Exception as e:
        await ctx.send(f"❌ Lỗi khi sao lưu: {e}")


# --- 24. LỆNH KHÔI PHỤC CẤU HÌNH SERVER ---
# Cú pháp: !khoi_phuc (đính kèm file backup_*.json)
# Lưu ý : Tạo một channel riêng để chạy lệnh này.
@bot.command(name="khoi_phuc")
@commands.has_permissions(administrator=True)
async def restore_config(ctx):
    """
    Khôi phục cấu hình server từ file JSON đính kèm.
    Tệp phải được đính kèm cùng lệnh (dạng backup_*.json).
    """
    if not ctx.message.attachments:
        await ctx.send("⚠️ Vui lòng đính kèm file backup JSON (tải từ lệnh `!sao_luu`).")
        return

    attachment = ctx.message.attachments[0]
    if not attachment.filename.endswith('.json'):
        await ctx.send("⚠️ File đính kèm phải có đuôi `.json`.")
        return

    try:
        raw = await attachment.read()
        data = json.loads(raw.decode('utf-8'))

        guild = ctx.guild
        command_channel = ctx.channel  # giữ lại kênh gốc

        # Xác nhận trước khi xóa
        confirm_msg = await ctx.send(
            "⚠️ **Cảnh báo:** Lệnh này sẽ **xóa tất cả vai trò (trừ @everyone) và kênh hiện có** "
            "để tái tạo từ file backup. Bạn có chắc không? Gõ `yes` để xác nhận trong 30 giây."
        )

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() == "yes"

        try:
            await bot.wait_for("message", check=check, timeout=30.0)
        except asyncio.TimeoutError:
            await ctx.send("⏰ Hết thời gian xác nhận. Hủy khôi phục.")
            return

        # ---- XÓA VAI TRÒ (ngoại trừ @everyone) ----
        await ctx.send("🔄 Đang xóa vai trò cũ...")
        for role in guild.roles:
            if role.is_default():
                continue
            try:
                await role.delete()
            except nextcord.Forbidden:
                print(f"Không thể xóa vai trò {role.name} (thiếu quyền). Bỏ qua.")
            except Exception as e:
                print(f"Lỗi khi xóa vai trò {role.name}: {e}. Bỏ qua.")

        # ---- XÓA KÊNH (giữ lại kênh hiện tại) ----
        await ctx.send("🔄 Đang xóa kênh cũ...")
        for channel in guild.channels:
            if channel.id == command_channel.id:
                continue
            await channel.delete()

        # ---- TẠO LẠI VAI TRÒ ----
        await ctx.send("🔄 Đang tạo vai trò mới...")
        role_map = {}  # old_id -> nextcord.Role
        # Thêm vai trò @everyone để áp dụng ghi đè sau này
        role_map[str(guild.id)] = guild.default_role  # ID @everyone chính là guild.id

        for r_data in data.get("roles", []):
            try:
                new_role = await guild.create_role(
                    name=r_data["name"],
                    color=nextcord.Color(r_data["color"]),
                    hoist=r_data["hoist"],
                    mentionable=r_data["mentionable"],
                    permissions=nextcord.Permissions(permissions=r_data["permissions"])
                )
                role_map[str(r_data["id"])] = new_role
            except Exception as e:
                print(f"Lỗi khi tạo vai trò {r_data['name']}: {e}")

        # ---- TẠO DANH MỤC ----
        await ctx.send("🔄 Đang tạo danh mục và kênh mới...")
        cat_map = {}  # old_id -> category
        for cat_data in data.get("categories", []):
            new_cat = await guild.create_category(
                name=cat_data["name"],
                position=cat_data.get("position", 0)
            )
            cat_map[str(cat_data["id"])] = new_cat
            await _apply_overwrites(new_cat, cat_data.get("overwrites", []), role_map)

        # ---- TẠO KÊNH ----
        for ch_data in data.get("channels", []):
            parent_id = ch_data.get("category_id")
            parent = cat_map.get(str(parent_id)) if parent_id else None
            ch_type = ch_data["type"]
            new_ch = None

            try:
                if ch_type == "text":
                    new_ch = await guild.create_text_channel(
                        name=ch_data["name"],
                        category=parent,
                        topic=ch_data.get("topic", ""),
                        slowmode_delay=ch_data.get("slowmode_delay", 0),
                        nsfw=ch_data.get("nsfw", False)
                    )
                elif ch_type == "voice":
                    new_ch = await guild.create_voice_channel(
                        name=ch_data["name"],
                        category=parent,
                        bitrate=ch_data.get("bitrate", 64000),
                        user_limit=ch_data.get("user_limit", 0)
                    )
                elif ch_type == "stage":
                    new_ch = await guild.create_stage_channel(
                        name=ch_data["name"],
                        category=parent,
                        topic=ch_data.get("topic", ""),
                        bitrate=ch_data.get("bitrate", 64000),
                        user_limit=ch_data.get("user_limit", 0)
                    )
                elif ch_type == "forum":
                    new_ch = await guild.create_forum_channel(
                        name=ch_data["name"],
                        category=parent,
                        topic=ch_data.get("topic", ""),
                        nsfw=ch_data.get("nsfw", False)
                    )
                else:
                    continue  # bỏ qua loại không xác định

                # Đặt vị trí (nếu cần)
                if "position" in ch_data:
                    await new_ch.edit(position=ch_data["position"])

                # Áp dụng phân quyền riêng
                await _apply_overwrites(new_ch, ch_data.get("overwrites", []), role_map)

            except Exception as e:
                print(f"Lỗi khi tạo kênh {ch_data['name']}: {e}")
                continue

        await ctx.send("✅ **Khôi phục cấu hình thành công!** (Kênh hiện tại được giữ lại)")

    except nextcord.Forbidden:
        await ctx.send("❌ Bot không có đủ quyền (Quản lý kênh, Quản lý vai trò) để khôi phục.")
    except json.JSONDecodeError:
        await ctx.send("❌ File JSON không hợp lệ. Hãy dùng file được tạo từ lệnh `!sao_luu`.")
    except Exception as e:
        await ctx.send(f"❌ Lỗi khi khôi phục: {e}")

# ----- Hàm tiện ích -----
def _serialize_overwrites(overwrites):
    """Chuyển danh sách PermissionOverwrite thành list dict để lưu JSON."""
    result = []
    for target, overwrite in overwrites.items():
        result.append({
            "type": "role" if isinstance(target, nextcord.Role) else "member",
            "id": target.id,
            "allow": overwrite.pair()[0].value,
            "deny": overwrite.pair()[1].value
        })
    return result


def _serialize_channel(channel, category_id):
    """Chuẩn hóa thông tin một kênh (text/voice/stage/forum)."""
    ch_type = None
    if isinstance(channel, nextcord.TextChannel):
        ch_type = "text"
    elif isinstance(channel, nextcord.VoiceChannel):
        ch_type = "voice"
    elif isinstance(channel, nextcord.StageChannel):
        ch_type = "stage"
    elif isinstance(channel, nextcord.ForumChannel):
        ch_type = "forum"
    else:
        ch_type = "unknown"

    return {
        "name": channel.name,
        "type": ch_type,
        "category_id": category_id,
        "topic": getattr(channel, "topic", ""),
        "overwrites": _serialize_overwrites(channel.overwrites)
    }


async def _apply_overwrites(channel, overwrites_data, role_map):
    """Áp dụng phân quyền từ dữ liệu backup vào kênh/danh mục."""
    guild = channel.guild
    for ow in overwrites_data:
        target = None
        if ow["type"] == "role":
            target = role_map.get(ow["id"])
            if target is None:
                continue  # role không tồn tại (bỏ qua)
        else:  # member
            # Người dùng có thể không còn trong server, tạm bỏ qua
            target = guild.get_member(ow["id"])
            if target is None:
                continue

        allow = nextcord.Permissions(permissions=ow["allow"])
        deny = nextcord.Permissions(permissions=ow["deny"])
        overwrite = nextcord.PermissionOverwrite.from_pair(allow, deny)
        await channel.set_permissions(target, overwrite=overwrite)

# --- 25.XUẤT LỊCH SỬ CHAT (ZIP) ---
@bot.command(name="xuat_log")
@commands.has_permissions(read_message_history=True)
async def export_log_zip(ctx, limit: str = "100"):
    """
    Xuất lịch sử chat ra file ZIP chứa tất cả file đính kèm gốc.
    """
    try:
        if limit.lower() == "all":
            limit_int = 1000
            await ctx.send("⚠️ Giới hạn 1000 tin nhắn gần nhất.")
        else:
            limit_int = int(limit)
            if limit_int < 1 or limit_int > 2000:
                await ctx.send("⚠️ Số lượng từ 1 đến 2000.")
                return
    except ValueError:
        await ctx.send("⚠️ Số lượng không hợp lệ.")
        return

    await ctx.send(f"🔄 Đang thu thập {limit_int} tin nhắn và tải file đính kèm...")
    
    messages = []
    # Lưu bytes của từng file với key = stored_name
    files_bytes = {}
    file_index = 0

    async with aiohttp.ClientSession() as session:
        async for msg in ctx.channel.history(limit=limit_int, oldest_first=False):
            attachments_info = []
            for att in msg.attachments:
                try:
                    async with session.get(att.url) as resp:
                        if resp.status == 200:
                            file_bytes = await resp.read()
                            # Giới hạn 5MB mỗi file (tùy chỉnh)
                            if len(file_bytes) > 5 * 1024 * 1024:
                                attachments_info.append({
                                    "filename": att.filename,
                                    "error": "File >5MB, bỏ qua"
                                })
                                continue
                            stored_name = f"{file_index}_{att.filename}"
                            files_bytes[stored_name] = file_bytes
                            attachments_info.append({
                                "filename": att.filename,
                                "stored_name": stored_name
                            })
                            file_index += 1
                        else:
                            attachments_info.append({
                                "filename": att.filename,
                                "error": f"HTTP {resp.status}"
                            })
                except Exception as e:
                    attachments_info.append({
                        "filename": att.filename,
                        "error": str(e)
                    })

            msg_data = {
                "author_name": msg.author.name,
                "author_id": msg.author.id,
                "content": msg.content,
                "timestamp": msg.created_at.isoformat(),
                "attachments": attachments_info
            }
            messages.append(msg_data)

    # Đảo thứ tự cũ -> mới
    messages.reverse()

    # Tạo ZIP trong buffer
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Ghi JSON
        zf.writestr('chat_log.json', json.dumps(messages, indent=2, ensure_ascii=False))
        # Ghi tất cả file đính kèm
        for stored_name, data in files_bytes.items():
            zf.writestr(f'files/{stored_name}', data)

    zip_buffer.seek(0)
    file_size_mb = len(zip_buffer.getvalue()) / (1024*1024)
    if file_size_mb > 7.9:
        await ctx.send("⚠️ File ZIP quá lớn (gần 8MB). Một số file đã bị bỏ qua hoặc bạn hãy giảm số lượng tin nhắn.")
        return

    await ctx.send(
        content=f"📦 **File sao lưu chat ({len(messages)} tin nhắn, {file_index} file)**",
        file=nextcord.File(zip_buffer, filename=f"chat_backup_{ctx.channel.id}.zip")
    )


# --- 26. PHỤC HỒI LỊCH SỬ CHAT (TỪ ZIP) ---
@bot.command(name="phuc_hoi_log")
@commands.has_permissions(send_messages=True, attach_files=True)
async def import_log_zip(ctx, channel: nextcord.TextChannel = None, *, delay: str = "1.5"):
    """
    Phát lại lịch sử chat từ file ZIP (tạo bởi !xuat_log).
    """
    if not ctx.message.attachments:
        await ctx.send("⚠️ Vui lòng đính kèm file ZIP (từ lệnh `!xuat_log`).")
        return

    attachment = ctx.message.attachments[0]
    if not attachment.filename.endswith('.zip'):
        await ctx.send("⚠️ File phải có đuôi `.zip`.")
        return

    target_channel = channel or ctx.channel
    if not target_channel.permissions_for(ctx.guild.me).send_messages:
        await ctx.send(f"❌ Bot không có quyền gửi tin nhắn vào {target_channel.mention}.")
        return

    try:
        delay_sec = float(delay)
        if delay_sec < 0.5:
            delay_sec = 0.5
    except ValueError:
        delay_sec = 1.5

    # Tải file ZIP vào bộ nhớ
    raw_bytes = await attachment.read()
    zip_buffer = io.BytesIO(raw_bytes)

    try:
        with zipfile.ZipFile(zip_buffer, 'r') as zf:
            # Đọc JSON
            json_data = zf.read('chat_log.json').decode('utf-8')
            messages = json.loads(json_data)
    except KeyError:
        await ctx.send("❌ File ZIP không chứa `chat_log.json`. Có phải file từ lệnh `!xuat_log`?")
        return
    except json.JSONDecodeError:
        await ctx.send("❌ JSON trong file ZIP không hợp lệ.")
        return

    total = len(messages)
    if total == 0:
        await ctx.send("❌ Không có tin nhắn nào.")
        return

    await ctx.send(f"🔄 Bắt đầu phát lại {total} tin nhắn vào {target_channel.mention} (delay {delay_sec}s)...")
    status_msg = await ctx.send(f"⏳ Tiến độ: 0/{total}")

    # Mở lại ZIP để đọc file (có thể dùng ZipFile trong with, nhưng cần đọc lại)
    # Để đơn giản, ta mở lại buffer
    zip_buffer.seek(0)
    with zipfile.ZipFile(zip_buffer, 'r') as zf:
        for index, msg_data in enumerate(messages, start=1):
            content = msg_data.get("content", "")
            author = msg_data.get("author_name", "Unknown")
            attachments_info = msg_data.get("attachments", [])

            # Định dạng nội dung
            formatted = f"**[{author}]**: {content}" if content.strip() else f"**[{author}]** *(không có nội dung)*"

            # Chuẩn bị danh sách file để gửi
            files = []
            for att in attachments_info:
                stored_name = att.get("stored_name")
                if stored_name:
                    try:
                        file_bytes = zf.read(f"files/{stored_name}")
                        files.append(nextcord.File(io.BytesIO(file_bytes), filename=att["filename"]))
                    except KeyError:
                        pass  # File không tồn tại trong ZIP, bỏ qua
                # Nếu có lỗi (error), có thể thêm vào nội dung
                # else: có thể thêm ghi chú

            # Gửi tin nhắn
            try:
                if files:
                    await target_channel.send(content=formatted, files=files)
                else:
                    await target_channel.send(content=formatted)
            except nextcord.Forbidden:
                await ctx.send(f"❌ Mất quyền gửi tin nhắn vào {target_channel.mention}. Dừng.")
                return
            except Exception as e:
                await ctx.send(f"❌ Lỗi khi gửi tin nhắn thứ {index}: {e}. Bỏ qua.")
                continue

            # Cập nhật tiến độ
            if index % 10 == 0 or index == total:
                try:
                    await status_msg.edit(content=f"⏳ Tiến độ: {index}/{total}")
                except:
                    pass

            await asyncio.sleep(delay_sec)

    await ctx.send(f"✅ Đã phát lại hoàn tất {total} tin nhắn vào {target_channel.mention}.")

# Đường dẫn file lưu cấu hình chào mừng (tự động tạo nếu chưa có)
WELCOME_CONFIG_PATH = "welcome_config.json"

def load_welcome_config():
    """Đọc cấu hình chào mừng từ file JSON."""
    if not os.path.exists(WELCOME_CONFIG_PATH):
        return {}
    with open(WELCOME_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_welcome_config(config):
    """Ghi cấu hình chào mừng vào file JSON."""
    with open(WELCOME_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

# --- 27. LỆNH THIẾT LẬP KÊNH CHÀO MỪNG & TIN NHẮN ---
# Cú pháp: !thiet_lap_chao_mung #kênh_chào_mừng [Nội dung tin nhắn] (dùng {user} để đề cập)
# Ví dụ: !thiet_lap_chao_mung #welcome Chào mừng {user} đã đến với server nhé!
@bot.command(name="thiet_lap_chao_mung")
@commands.has_permissions(manage_guild=True)
async def thiet_lap_chao_mung(ctx, channel: nextcord.TextChannel, *, message: str = None):
    """
    Thiết lập kênh và tin nhắn chào mừng cho máy chủ.
    Nếu không truyền message, bot sẽ xóa thiết lập chào mừng của server.
    """
    guild_id = str(ctx.guild.id)
    config = load_welcome_config()

    try:
        if message is None:
            # Xóa cấu hình nếu không có message
            if guild_id in config:
                del config[guild_id]
                save_welcome_config(config)
                await ctx.send("🗑️ Đã xóa thiết lập chào mừng của server.")
            else:
                await ctx.send("⚠️ Server hiện chưa có thiết lập chào mừng.")
            return

        # Lưu cấu hình
        config[guild_id] = {
            "channel_id": channel.id,
            "message": message
        }
        save_welcome_config(config)

        await ctx.send(
            f"✅ Đã thiết lập kênh chào mừng: {channel.mention}\n"
            f"📝 Nội dung tin nhắn: `{message}`\n"
            f"(Dùng `{{user}}` để đề cập thành viên mới, `{{server}}` để hiển thị tên server)"
        )
    except nextcord.Forbidden:
        await ctx.send("❌ Bot không có quyền gửi tin nhắn vào kênh đó hoặc thiếu quyền quản lý.")
    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi: {e}")

# --- SỰ KIỆN: GỬI TIN NHẮN CHÀO MỪNG KHI CÓ THÀNH VIÊN MỚI ---
@bot.event
async def on_member_join(member):
    config = load_welcome_config()
    guild_id = str(member.guild.id)

    if guild_id not in config:
        return  # Không có thiết lập chào mừng

    channel_id = config[guild_id]["channel_id"]
    raw_message = config[guild_id]["message"]

    channel = member.guild.get_channel(channel_id)
    if channel is None:
        return  # Kênh đã bị xóa

    # Thay thế placeholder
    welcome_text = raw_message.replace("{user}", member.mention)
    welcome_text = welcome_text.replace("{server}", member.guild.name)

    try:
        await channel.send(welcome_text)
    except nextcord.Forbidden:
        pass  # Không có quyền gửi, bỏ qua

# --- 28. LỆNH SAO CHÉP KÊNH (Clone kênh giữ nguyên cấu trúc, quyền, danh mục) ---
# Cú pháp: !sao_chep_kenh <kênh_gốc> <tên_mới>
# Ví dụ: !sao_chep_kenh #general "Phòng Chat Vip"
@bot.command(name="sao_chep_kenh")
@commands.has_permissions(manage_channels=True)
async def sao_chep_kenh(ctx, channel: nextcord.abc.GuildChannel, *, ten_moi: str):
    """Sao chép một kênh (text/voice/stage/forum) sang kênh mới cùng danh mục và quyền."""
    try:
        guild = ctx.guild

        # Không cho phép sao chép danh mục (CategoryChannel)
        if isinstance(channel, nextcord.CategoryChannel):
            await ctx.send("⚠️ Không hỗ trợ sao chép danh mục. Vui lòng chọn một kênh cụ thể.")
            return

        # Xác định loại kênh và tạo bản sao tương ứng
        # Lấy danh mục gốc để gán cho kênh mới
        parent_category = channel.category

        # Tạo kênh mới với các thuộc tính chính
        if isinstance(channel, nextcord.TextChannel):
            new_channel = await guild.create_text_channel(
                name=ten_moi,
                category=parent_category,
                topic=channel.topic,
                nsfw=channel.nsfw,
                slowmode_delay=channel.slowmode_delay,
                overwrites=channel.overwrites,          # sao chép toàn bộ quyền
                reason=f"Sao chép từ {channel.name} bởi {ctx.author}"
            )
        elif isinstance(channel, nextcord.VoiceChannel):
            new_channel = await guild.create_voice_channel(
                name=ten_moi,
                category=parent_category,
                bitrate=channel.bitrate,
                user_limit=channel.user_limit,
                overwrites=channel.overwrites,
                reason=f"Sao chép từ {channel.name} bởi {ctx.author}"
            )
            # Sao chép thêm region và video quality nếu có (phải edit sau)
            if channel.rtc_region:
                await new_channel.edit(rtc_region=channel.rtc_region)
            if hasattr(channel, 'video_quality_mode') and channel.video_quality_mode:
                await new_channel.edit(video_quality_mode=channel.video_quality_mode)
        elif isinstance(channel, nextcord.StageChannel):
            new_channel = await guild.create_stage_channel(
                name=ten_moi,
                category=parent_category,
                topic=channel.topic,
                bitrate=channel.bitrate,
                user_limit=channel.user_limit,
                overwrites=channel.overwrites,
                reason=f"Sao chép từ {channel.name} bởi {ctx.author}"
            )
            if channel.rtc_region:
                await new_channel.edit(rtc_region=channel.rtc_region)
        elif isinstance(channel, nextcord.ForumChannel):
            # Forum không có nsfw, slowmode_delay có thể None -> 0
            slowmode = channel.slowmode_delay if channel.slowmode_delay else 0
            new_channel = await guild.create_forum_channel(
                name=ten_moi,
                category=parent_category,
                topic=channel.topic,
                slowmode_delay=slowmode,
                overwrites=channel.overwrites,
                reason=f"Sao chép từ {channel.name} bởi {ctx.author}"
            )
        else:
            await ctx.send("⚠️ Loại kênh này hiện chưa được hỗ trợ sao chép.")
            return

        await ctx.send(
            f"✅ Đã sao chép kênh {channel.mention} thành {new_channel.mention} "
            f"với tên **{ten_moi}** (giữ nguyên danh mục, quyền và cấu trúc)."
        )

    except nextcord.Forbidden:
        await ctx.send("❌ Bot không có đủ quyền `Manage Channels` để thực hiện.")
    except nextcord.HTTPException as e:
        await ctx.send(f"❌ Lỗi từ Discord API: {e}")
    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi không xác định: {e}")

# --- 29. LỆNH ĐẶT CHẾ ĐỘ CHẬM (SLOWMODE) ---
# Cú pháp: !che_do_cham [kênh] [thời_gian_giây]
# Ví dụ: !che_do_cham #chung 10  (đặt slowmode 10 giây cho kênh #chung)
@bot.command(name="che_do_cham")
@commands.has_permissions(manage_channels=True)
async def che_do_cham(ctx, channel: nextcord.TextChannel, thoi_gian: int):
    """Đặt chế độ chậm (slowmode) cho kênh văn bản."""
    try:
        # Giới hạn slowmode của Discord: 0s (tắt) đến 21600s (6 giờ)
        if thoi_gian < 0 or thoi_gian > 21600:
            await ctx.send("⚠️ Thời gian slowmode phải nằm trong khoảng từ **0** đến **21600** giây!")
            return

        await channel.edit(slowmode_delay=thoi_gian)

        if thoi_gian == 0:
            await ctx.send(f"✅ Đã tắt chế độ chậm cho kênh {channel.mention}.")
        else:
            await ctx.send(f"✅ Đã đặt chế độ chậm **{thoi_gian} giây** cho kênh {channel.mention}.")

    except nextcord.Forbidden:
        await ctx.send("❌ Bot không có đủ quyền `Manage Channels` để chỉnh slowmode ở kênh này.")
    except AttributeError:
        await ctx.send("❌ Kênh được chỉ định không phải là kênh văn bản (chỉ kênh văn bản mới hỗ trợ slowmode).")
    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi khi đặt chế độ chậm: {e}")

# --- 30. LỆNH SAO CHÉP VAI TRÒ (Copy Role) ---
# Cú pháp: !sao_chep_vai_tro <vai_trò_nguồn> <tên_mới>
# Ví dụ:   !sao_chep_vai_tro @Moderator Mod-Copy
@bot.command(name="sao_chep_vai_tro")
@commands.has_permissions(manage_roles=True)
async def sao_chep_vai_tro(ctx, role: nextcord.Role, *, ten_moi: str):
    """Sao chép toàn bộ quyền, màu sắc, cài đặt hiển thị của một vai trò sang vai trò mới."""
    try:
        guild = ctx.guild

        # Kiểm tra phân cấp: bot chỉ có thể sao chép những vai trò thấp hơn vai trò cao nhất của mình
        if role >= guild.me.top_role:
            await ctx.send("❌ Vai trò nguồn cao hơn hoặc bằng vai trò cao nhất của bot. Không thể sao chép.")
            return

        # Tạo vai trò mới với các thuộc tính giống hệt
        new_role = await guild.create_role(
            name=ten_moi,
            permissions=role.permissions,
            color=role.color,
            hoist=role.hoist,            # Hiển thị riêng biệt
            mentionable=role.mentionable, # Có thể @mention
            reason=f"Được sao chép từ vai trò {role.name} bởi {ctx.author}"
        )

        # (Tùy chọn) Không thay đổi vị trí – vai trò mới được đặt ở cuối danh sách.
        # Nếu bạn muốn đặt ngay dưới vai trò nguồn, có thể bỏ comment dòng dưới.
        # Nhưng cần đảm bảo vị trí mới nhỏ hơn guild.me.top_role.position.
        # if role.position + 1 < guild.me.top_role.position:
        #     await new_role.edit(position=role.position + 1)

        await ctx.send(
            f"✨ Đã sao chép thành công vai trò **{role.name}** → **{new_role.name}**!\n"
            f"🔹 Quyền, màu sắc, cài đặt hiển thị được giữ nguyên.\n"
            f"🔸 Vai trò mới nằm ở cuối danh sách (có thể kéo lên thủ công)."
        )

    except nextcord.Forbidden:
        await ctx.send("❌ Bot không có đủ quyền `Manage Roles` để tạo vai trò mới.")
    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi khi sao chép vai trò: {e}")

# --- 31. LỆNH HIỂN THỊ TOÀN BỘ QUYỀN CỦA NGƯỜI DÙNG ---
# Cú pháp: !quyen [@nguoi_dung]
# Ví dụ: !quyen @ThanhVien
@bot.command(name="quyen")
async def hien_thi_quyen(ctx, member: nextcord.Member = None):
    if member is None:
        member = ctx.author

    # 1. Quyền hiệu lực cuối cùng trong kênh
    effective_perms = ctx.channel.permissions_for(member)

    # 2. Ghi đè kênh riêng cho thành viên này (nếu có)
    overwrite = ctx.channel.overwrites_for(member)

    # --- Tạo danh sách quyền hiệu lực ---
    perm_lines = []
    for perm_name in nextcord.Permissions.VALID_FLAGS:
        has_perm = getattr(effective_perms, perm_name)
        icon = "✅" if has_perm else "❌"
        readable = perm_name.replace('_', ' ').title()
        perm_lines.append(f"{icon} {readable}")

    embed = nextcord.Embed(
        title=f"📋 Quyền của {member.display_name}",
        color=0x3498db
    )
    embed.add_field(
        name="🔹 Quyền hiệu lực (trong kênh này)",
        value="\n".join(perm_lines) if perm_lines else "Không có quyền nào",
        inline=False
    )

    # --- Thêm thông tin ghi đè kênh (nếu có) ---
    if overwrite:
        # Lọc ra những quyền được Allow hoặc Deny trong ghi đè
        allow_list = [p.replace('_', ' ').title() for p, v in overwrite if v is True]
        deny_list = [p.replace('_', ' ').title() for p, v in overwrite if v is False]

        overwrite_text = ""
        if allow_list:
            overwrite_text += f"**🟢 Allow:** {', '.join(allow_list)}\n"
        if deny_list:
            overwrite_text += f"**🔴 Deny:** {', '.join(deny_list)}\n"
        if not overwrite_text:
            overwrite_text = "Không có ghi đè đặc biệt (trung lập)."
        embed.add_field(
            name="⚙️ Ghi đè kênh riêng cho user này",
            value=overwrite_text,
            inline=False
        )
    else:
        embed.add_field(
            name="⚙️ Ghi đè kênh riêng",
            value="Không có ghi đè riêng nào được thiết lập.",
            inline=False
        )

    # Kiểm tra nhanh quyền Administrator
    if effective_perms.administrator:
        embed.add_field(
            name="⚠️ Cảnh báo",
            value="Thành viên này có quyền **Administrator** – tất cả quyền khác đều tự động được phép, mọi deny đều vô hiệu.",
            inline=False
        )

    embed.set_footer(text=f"Kiểm tra trong kênh: #{ctx.channel.name}")
    await ctx.send(embed=embed)

# --- 32. LỆNH THIẾT LẬP GHI ĐÈ QUYỀN CỦA KÊNH ---
# Cú pháp: !set_quyen [@thành_viên] [#kênh] [quyền] [chế_độ]
# Ví dụ: !set_quyen @User #general view_channel allow
@bot.command(name="set_quyen")
@commands.has_permissions(manage_channels=True)
async def set_quyen(ctx, member: nextcord.Member, channel: nextcord.abc.GuildChannel, permission: str, mode: str):
    """
    Thiết lập ghi đè quyền cụ thể cho một thành viên trên một kênh.
    Chế độ: "allow" (cho phép), "deny" (từ chối), "default" (xóa ghi đè).
    """
    try:
        # Chuyển đổi tên quyền thành thuộc tính của nextcord.Permissions
        permission = permission.lower()
        valid_perms = {
            'view_channel', 'send_messages', 'read_messages', 'connect',
            'speak', 'mute_members', 'deafen_members', 'move_members',
            'use_voice_activation', 'priority_speaker', 'stream',
            'embed_links', 'attach_files', 'read_message_history',
            'mention_everyone', 'use_external_emojis', 'add_reactions',
            'manage_messages', 'manage_webhooks', 'manage_channels',
            'kick_members', 'ban_members', 'administrator'
        }
        if permission not in valid_perms:
            await ctx.send(f"⚠️ Quyền `{permission}` không hợp lệ. Hãy dùng tên quyền viết thường, ví dụ: `view_channel`, `send_messages`.")
            return

        # Lấy ghi đè hiện tại của thành viên trên kênh (nếu có) hoặc tạo mới
        overwrite = channel.overwrites_for(member)
        
        # Cập nhật quyền cụ thể
        mode = mode.lower()
        if mode == "allow":
            setattr(overwrite, permission, True)
        elif mode == "deny":
            setattr(overwrite, permission, False)
        elif mode == "default":
            setattr(overwrite, permission, None)  # Xoá ghi đè của quyền này
        else:
            await ctx.send("⚠️ Chế độ không hợp lệ. Sử dụng: `allow`, `deny`, hoặc `default`.")
            return

        # Áp dụng ghi đè đã sửa đổi lên kênh
        await channel.set_permissions(member, overwrite=overwrite)
        await ctx.send(f"✅ Đã cập nhật quyền `{permission}` cho {member.mention} trên kênh {channel.mention} sang chế độ `{mode}`.")
    
    except nextcord.Forbidden:
        await ctx.send("❌ Bot không có đủ quyền `Manage Channels` để sửa ghi đè quyền.")
    except Exception as e:
        await ctx.send(f"❌ Lỗi: {e}")

# --- 33. LỆNH PING (WEBSOCKET & DISCORD API LATENCY) ---
# Cú pháp: !ping
# Ví dụ: !ping
@bot.command(name="ping")
async def ping(ctx):
    """Hiển thị độ trễ WebSocket và API của bot."""
    # Độ trễ WebSocket (heartbeat)
    ws_latency = round(bot.latency * 1000)  # ms
    # Đo độ trễ API bằng cách gửi và sửa tin nhắn
    start = time.perf_counter()
    msg = await ctx.send("🏓 Đang đo...")
    end = time.perf_counter()
    api_latency = round((end - start) * 1000)
    await msg.edit(content=f"🏓 Pong!\n**WebSocket:** {ws_latency}ms\n**API:** {api_latency}ms")

# --- 34. LỆNH TỰ ĐỘNG XÓA TIN NHẮN ---
# Cú pháp: !tu_dong_xoa <#kênh> <thời_gian_giây | off>
# Ví dụ: !tu_dong_xoa #chung 10 (xóa sau 10 giây), !tu_dong_xoa #chung off (tắt)
@bot.command(name="tu_dong_xoa")
@commands.has_permissions(manage_messages=True)
async def tu_dong_xoa(ctx, channel: nextcord.TextChannel, thoi_gian: str):
    """Bật/tắt tự động xóa tin nhắn trong kênh sau khoảng thời gian (giây)."""
    try:
        guild = ctx.guild
        # Kiểm tra bot có quyền xóa tin nhắn trong kênh đó không
        if not channel.permissions_for(guild.me).manage_messages:
            await ctx.send("❌ Bot không có quyền `Manage Messages` trong kênh này.")
            return

        if thoi_gian.lower() == "off":
            # Tắt tự động xóa
            if channel.id in auto_delete_channels:
                del auto_delete_channels[channel.id]
                await ctx.send(f"🛑 Đã **tắt** tự động xóa tin nhắn trong {channel.mention}.")
            else:
                await ctx.send(f"ℹ️ Tự động xóa chưa được bật trong {channel.mention}.")
            return

        # Chuyển sang số nguyên (giây)
        try:
            delay = int(thoi_gian)
        except ValueError:
            await ctx.send("⚠️ Thời gian phải là một số nguyên (giây) hoặc `off`.")
            return

        if delay < 1:
            await ctx.send("⚠️ Thời gian phải lớn hơn 0 giây.")
            return

        # Lưu cấu hình
        auto_delete_channels[channel.id] = delay
        await ctx.send(f"⏱️ Đã **bật** tự động xóa tin nhắn trong {channel.mention} sau **{delay}** giây.")

    except Exception as e:
        await ctx.send(f"❌ Lỗi khi thiết lập tự động xóa: {e}")


# Sự kiện xử lý tin nhắn mới để tự động xóa
@bot.event
async def on_message(message):
    # Bỏ qua tin nhắn của bot để tránh vòng lặp
    if message.author.bot:
        return

    # Kiểm tra nếu kênh hiện tại có trong danh sách tự động xóa
    if message.channel.id in auto_delete_channels:
        delay = auto_delete_channels[message.channel.id]

        # Tạo tác vụ chờ và xóa tin nhắn (không chặn luồng chính)
        async def delete_after_delay():
            await asyncio.sleep(delay)
            try:
                await message.delete()
            except nextcord.NotFound:
                pass  # Tin nhắn đã bị xóa trước đó
            except nextcord.Forbidden:
                # Quyền bị thu hồi, có thể thông báo lỗi hoặc âm thầm xóa cấu hình
                pass

        bot.loop.create_task(delete_after_delay())

    # Quan trọng: cho phép các lệnh khác tiếp tục hoạt động
    await bot.process_commands(message)

# --- 35. LỆNH GỬI TIN NHẮN ẨN DANH (QUẢN TRỊ) ---
# Cú pháp: !tin_an_danh [kênh] <nội dung>
# Ví dụ:   !tin_an_danh #thông-báo Máy chủ sẽ bảo trì lúc 22h00
@bot.command(name="tin_an_danh")
@commands.has_permissions(manage_messages=True)
async def anon(ctx, channel: nextcord.TextChannel = None, *, message: str):
    """Gửi tin nhắn ẩn danh dưới tên bot, xoá lệnh gốc để bảo mật danh tính."""
    try:
        # Nếu không chỉ định kênh, dùng chính kênh hiện tại
        if channel is None:
            channel = ctx.channel

        # Gửi tin nhắn ẩn danh vào kênh đích
        await channel.send(message)

        # Xóa lệnh gốc của người dùng để ẩn danh hoàn toàn
        await ctx.message.delete()

    except nextcord.Forbidden:
        await ctx.send("❌ Bot không có quyền gửi tin nhắn vào kênh đích hoặc không xóa được tin nhắn.")
    except nextcord.HTTPException:
        await ctx.send("❌ Không thể gửi tin nhắn (lỗi HTTP).")
    except Exception as e:
        await ctx.send(f"❌ Lỗi không xác định: {e}")

# --- 36. LỆNH XEM NHẬT KÝ KIỂM DUYỆT (AUDIT LOG) ---
# Cú pháp: !xem_nhatky [số_lượng]
# Ví dụ:   !xem_nhatky 5
@bot.command(name="xem_nhatky")
@commands.has_permissions(view_audit_log=True)
async def xem_nhatky(ctx, so_luong: int = 10):
    """Hiển thị các mục gần đây nhất từ Audit Log của server."""
    try:
        # Giới hạn số lượng mục để tránh spam
        if so_luong < 1:
            so_luong = 1
        elif so_luong > 20:
            so_luong = 20
            await ctx.send("⚠️ Số lượng quá lớn, mình sẽ chỉ hiển thị tối đa 20 mục gần đây nhất.")

        guild = ctx.guild
        audit_entries = []

        # Lấy các mục audit log
        async for entry in guild.audit_logs(limit=so_luong):
            # Lấy thông tin chi tiết
            hanh_dong = entry.action.name.replace("_", " ").title()
            nguoi_thuc_hien = entry.user.mention if entry.user else "Không xác định"
            muc_tieu = str(entry.target) if entry.target else "Không xác định"
            ly_do = entry.reason or "Không có"
            thoi_gian = nextcord.utils.format_dt(entry.created_at, style="F")

            audit_entries.append(
                f"**Hành động:** {hanh_dong}\n"
                f"**Người thực hiện:** {nguoi_thuc_hien}\n"
                f"**Mục tiêu:** {muc_tieu}\n"
                f"**Lý do:** {ly_do}\n"
                f"**Thời gian:** {thoi_gian}"
            )

        if not audit_entries:
            await ctx.send("📭 Không có mục nào trong nhật ký kiểm duyệt.")
            return

        # Chia thành các embed nhỏ nếu dữ liệu dài (mỗi mục một field)
        embeds = []
        current_embed = nextcord.Embed(
            title=f"📋 Nhật Ký Kiểm Duyệt ({so_luong} mục gần đây)",
            color=0x3498db
        )
        field_count = 0

        for i, entry_text in enumerate(audit_entries, 1):
            # Mỗi embed Discord tối đa 25 fields
            if field_count >= 25:
                embeds.append(current_embed)
                current_embed = nextcord.Embed(
                    title=f"📋 Nhật Ký Kiểm Duyệt (tiếp theo)",
                    color=0x3498db
                )
                field_count = 0

            current_embed.add_field(
                name=f"Mục {i}",
                value=entry_text,
                inline=False
            )
            field_count += 1

        embeds.append(current_embed)

        # Gửi từng embed
        for embed in embeds:
            await ctx.send(embed=embed)

    except nextcord.Forbidden:
        await ctx.send("❌ Bot không có quyền `View Audit Log` để xem nhật ký kiểm duyệt.")
    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi khi lấy audit log: {e}")

# --- 37. LỆNH KIỂM TRA SỨC KHOẺ SERVER ---
# Cú pháp: !tinh_trang
# Ví dụ: !tinh_trang
@bot.command(name="tinh_trang")
async def tinh_trang(ctx):
    """Hiển thị toàn diện tình trạng server, đảm bảo không vượt quá 25 fields."""
    try:
        guild = ctx.guild

        # --- 1. Độ trễ bot ---
        ping_ms = round(bot.latency * 1000)

        # --- 2. Thành viên & trạng thái ---
        total_members = guild.member_count
        humans = 0
        bots = 0
        online = 0
        idle = 0
        dnd = 0
        offline = 0

        for member in guild.members:
            if member.bot:
                bots += 1
            else:
                humans += 1

            status = member.status
            if status == nextcord.Status.online:
                online += 1
            elif status == nextcord.Status.idle:
                idle += 1
            elif status == nextcord.Status.dnd:
                dnd += 1
            else:
                offline += 1

        # --- 3. Thống kê kênh ---
        text_channels = guild.text_channels
        voice_channels = guild.voice_channels
        stage_channels = guild.stage_channels
        forum_channels = guild.forum_channels
        categories = guild.categories

        total_text = len(text_channels)
        total_voice = len(voice_channels)
        total_stage = len(stage_channels)
        total_forum = len(forum_channels)
        total_categories = len(categories)
        total_channels = total_text + total_voice + total_stage + total_forum

        # Kênh không dùng
        unused_text = sum(1 for ch in text_channels if ch.last_message is None)
        unused_voice = sum(1 for ch in voice_channels if len(ch.members) == 0)
        unused_stage = sum(1 for ch in stage_channels if len(ch.members) == 0)
        unused_forum = sum(1 for ch in forum_channels if len(ch.threads) == 0)
        total_unused = unused_text + unused_voice + unused_stage + unused_forum

        # --- 4. Vai trò trống ---
        empty_roles = 0
        for role in guild.roles:
            if not role.is_default() and len(role.members) == 0:
                empty_roles += 1

        # --- 5. Thông tin nâng cao ---
        verification_levels = {
            nextcord.VerificationLevel.none: "Không",
            nextcord.VerificationLevel.low: "Thấp (email)",
            nextcord.VerificationLevel.medium: "Vừa (email + 5 phút)",
            nextcord.VerificationLevel.high: "Cao (email + 5 phút + server 10 phút)",
            nextcord.VerificationLevel.highest: "Rất cao (cần SĐT)"
        }
        verification = verification_levels.get(guild.verification_level, "?")
        content_filters = {
            nextcord.ContentFilter.disabled: "Tắt",
            nextcord.ContentFilter.no_role: "Thành viên không vai trò",
            nextcord.ContentFilter.all_members: "Tất cả thành viên"
        }
        content_filter = content_filters.get(guild.explicit_content_filter, "?")
        mfa = "Có" if guild.mfa_level == 1 else "Không"

        boost_count = guild.premium_subscription_count
        boost_tier = guild.premium_tier

        afk_channel = guild.afk_channel
        afk_timeout = guild.afk_timeout
        afk_display = f"{afk_channel.mention} ({afk_timeout//60} phút)" if afk_channel else "Không có"

        system_channel = guild.system_channel
        sys_chan_display = system_channel.mention if system_channel else "Không có"
        rules_channel = guild.rules_channel
        rules_display = rules_channel.mention if rules_channel else "Không có"
        public_updates = guild.public_updates_channel
        public_display = public_updates.mention if public_updates else "Không có"

        created_at = guild.created_at.strftime("%d/%m/%Y %H:%M:%S")

        # --- 6. Xây dựng Embed (chỉ 10 fields) ---
        embed = nextcord.Embed(
            title=f"📊 Sức khoẻ máy chủ **{guild.name}**",
            color=0x2F3136,
            timestamp=ctx.message.created_at
        )
        embed.set_thumbnail(url=guild.icon.url if guild.icon else None)

        # Field 1: Độ trễ
        embed.add_field(name="⏱️ Độ trễ Bot", value=f"`{ping_ms} ms`", inline=True)

        # Field 2: Tổng thành viên & Người/Bot
        embed.add_field(
            name="👥 Thành viên",
            value=f"Tổng: `{total_members}`\nNgười: `{humans}` | Bot: `{bots}`",
            inline=True
        )

        # Field 3: Trạng thái (gộp 4 trạng thái vào 1 field)
        embed.add_field(
            name="📶 Trạng thái",
            value=f"🟢 `{online}`  🌙 `{idle}`  ⛔ `{dnd}`  ⚫ `{offline}`",
            inline=True
        )

        # Field 4: Kênh (gộp tất cả loại kênh)
        embed.add_field(
            name="💬 Kênh",
            value=f"Text: `{total_text}`\nVoice: `{total_voice}`\nStage: `{total_stage}`\nForum: `{total_forum}`\nDanh mục: `{total_categories}`\n**Tổng:** `{total_channels}`",
            inline=True
        )

        # Field 5: Kênh không dùng (gộp chi tiết)
        embed.add_field(
            name="🗑️ Kênh không dùng",
            value=f"**Tổng:** `{total_unused}`\nText trống: `{unused_text}`\nVoice trống: `{unused_voice}`\nStage trống: `{unused_stage}`\nForum trống: `{unused_forum}`",
            inline=True
        )

        # Field 6: Vai trò
        embed.add_field(
            name="🎭 Vai trò",
            value=f"Tổng: `{len(guild.roles)}`\nKhông người: `{empty_roles}`",
            inline=True
        )

        # Field 7: Bảo mật & Xác minh (gộp 3 mục)
        embed.add_field(
            name="🛡️ Bảo mật",
            value=f"Xác minh: `{verification}`\nLọc ND: `{content_filter}`\n2FA mod: `{mfa}`",
            inline=True
        )

        # Field 8: Boost
        embed.add_field(
            name="🚀 Boost",
            value=f"Số boost: `{boost_count}`\nCấp: `{boost_tier}`",
            inline=True
        )

        # Field 9: AFK + Kênh đặc biệt (gộp 4 thông tin)
        embed.add_field(
            name="⚙️ Cấu hình khác",
            value=f"AFK: {afk_display}\nHệ thống: {sys_chan_display}\nNội quy: {rules_display}\nCập nhật: {public_display}",
            inline=False
        )

        # Field 10: Ngày tạo server
        embed.add_field(
            name="📅 Ngày tạo",
            value=f"`{created_at}`",
            inline=False
        )

        embed.set_footer(text=f"Yêu cầu bởi {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"❌ Không thể kiểm tra tình trạng server: {e}")

# --- 38. LỆNH BẬT HỆ THỐNG XÁC MINH ---
# Cú pháp: !bat_xac_minh [Kênh] [Nội dung tin nhắn]
# Ví dụ: !bat_xac_minh #xác-minh Nhấn ✅ để xác nhận bạn là người!

@bot.command(name="bat_xac_minh")
@commands.has_permissions(manage_guild=True)
async def bat_xac_minh(ctx, channel: nextcord.TextChannel, *, content: str):
    """Bật hệ thống xác minh: gửi tin nhắn có phản ứng, ai nhấn sẽ được role Verified."""
    try:
        guild = ctx.guild

        # --- Kiểm tra quyền của bot ---
        if not guild.me.guild_permissions.manage_roles:
            await ctx.send("❌ Bot cần quyền `Manage Roles` để cấp role xác minh.")
            return
        if not channel.permissions_for(guild.me).send_messages or not channel.permissions_for(guild.me).add_reactions:
            await ctx.send("❌ Bot không có quyền gửi tin nhắn hoặc thêm phản ứng trong kênh đó.")
            return

        # --- Lấy hoặc tạo role "Verified" ---
        verified_role = nextcord.utils.get(guild.roles, name="Verified")
        if verified_role is None:
            verified_role = await guild.create_role(
                name="Verified",
                reason="Hệ thống xác minh tự động",
                colour=nextcord.Color.green()
            )
            await ctx.send("ℹ️ Đã tạo role `Verified` vì chưa tồn tại.")

        # --- Gửi tin nhắn xác minh và thêm phản ứng ---
        verify_msg = await channel.send(content)
        emoji = "✅"
        await verify_msg.add_reaction(emoji)

        # --- Lưu cấu hình (chỉ lưu 1 hệ thống duy nhất cho mỗi máy chủ) ---
        verify_config[str(guild.id)] = {
            "message_id": verify_msg.id,
            "channel_id": channel.id,
            "role_id": verified_role.id,
            "emoji": emoji
        }
        save_verify_config()

        await ctx.send(f"✅ Đã bật hệ thống xác minh tại {channel.mention}. Nội dung: {content}")

    except nextcord.Forbidden:
        await ctx.send("❌ Bot không có đủ quyền để thực hiện thao tác này.")
    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi: {e}")


# ---  SỰ KIỆN XỬ LÝ KHI NGƯỜI DÙNG NHẤN PHẢN ỨNG ---
@bot.event
async def on_raw_reaction_add(payload: nextcord.RawReactionActionEvent):
    """Khi có người thêm phản ứng vào tin nhắn xác minh, cấp role Verified."""
    # Bỏ qua nếu người thêm phản ứng là bot
    if payload.member is None or payload.member.bot:
        return

    guild_id = str(payload.guild_id)
    if guild_id not in verify_config:
        return

    config = verify_config[guild_id]
    # Kiểm tra đúng tin nhắn và đúng biểu tượng
    if payload.message_id != config["message_id"]:
        return
    if str(payload.emoji) != config["emoji"]:
        return

    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return

    role = guild.get_role(config["role_id"])
    if role is None:
        return

    member = payload.member
    if role in member.roles:
        # Đã có role – có thể báo DM hoặc không làm gì
        try:
            await member.send("ℹ️ Bạn đã được xác minh trước đó rồi!")
        except:
            pass
        return

    try:
        await member.add_roles(role, reason="Xác minh qua phản ứng")
        # Có thể thông báo cho thành viên qua DM
        try:
            await member.send(f"✅ Bạn đã được xác minh trong **{guild.name}**!")
        except:
            pass
    except nextcord.Forbidden:
        # Ghi log lỗi nếu cần, không spam kênh
        print(f"Không thể cấp role Verified cho {member} vì thiếu quyền.")

# --- 39. LỆNH TẠO THĂM DÒ (POLL) ---
# Cú pháp: !poll <câu hỏi> | <lựa chọn 1> | <lựa chọn 2> | ...
# Ví dụ: !poll "Bạn thích ngôn ngữ nào?" | Python | JavaScript | C++
@bot.command(name="poll")
async def poll(ctx, *, args: str):
    """
    Tạo một cuộc thăm dò ý kiến với các lựa chọn được phân cách bởi dấu '|'.
    Tối đa 10 lựa chọn. Bot sẽ tự động thêm biểu tượng cảm xúc (🇦, 🇧, ...) cho mỗi lựa chọn.
    """
    try:
        # Tách câu hỏi và các lựa chọn
        parts = [p.strip() for p in args.split('|')]
        if len(parts) < 3:
            await ctx.send("⚠️ Vui lòng cung cấp ít nhất một câu hỏi và 2 lựa chọn.\n"
                           "Cú pháp: `!poll <câu hỏi> | <lựa chọn 1> | <lựa chọn 2> | ...`")
            return

        question = parts[0]
        options = parts[1:]

        if len(options) > 10:
            await ctx.send("⚠️ Tối đa 10 lựa chọn được hỗ trợ.")
            return

        # Danh sách biểu tượng cảm xúc khu vực (regional indicators)
        indicator_emojis = ['🇦', '🇧', '🇨', '🇩', '🇪', '🇫', '🇬', '🇭', '🇮', '🇯']

        # Tạo Embed đẹp mắt
        embed = nextcord.Embed(
            title="📊 Thăm Dò Ý Kiến",
            description=question,
            color=0x3498db
        )

        option_lines = []
        for i, option in enumerate(options):
            emoji = indicator_emojis[i]
            option_lines.append(f"{emoji}  {option}")

        embed.add_field(
            name="Các lựa chọn",
            value="\n".join(option_lines),
            inline=False
        )
        embed.set_footer(text=f"Được tạo bởi {ctx.author.display_name} • Dùng emoji để bình chọn")

        # Gửi embed và thêm reaction
        poll_message = await ctx.send(embed=embed)
        for i in range(len(options)):
            await poll_message.add_reaction(indicator_emojis[i])

    except nextcord.Forbidden:
        await ctx.send("❌ Bot không có quyền gửi tin nhắn hoặc thêm reaction trong kênh này.")
    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi khi tạo thăm dò: {e}")

# --- 40. LỆNH GỬI TIN NHẮN NHÚNG ---
# Cú pháp: !gui_nhung <tiêu đề> | <mô tả> | <mã màu hex (tuỳ chọn)>
# Ví dụ: !gui_nhung Xin chào | Đây là nội dung embed | #ff5733
@bot.command(name="gui_nhung")
async def gui_nhung(ctx, *, args: str):
    """Gửi một tin nhắn nhúng (embed) với tiêu đề, mô tả và màu sắc tuỳ chọn."""
    try:
        # Tách tham số theo dấu '|'
        parts = [p.strip() for p in args.split('|')]
        
        # Gán giá trị mặc định nếu thiếu
        title = parts[0] if len(parts) > 0 and parts[0] else "Không có tiêu đề"
        description = parts[1] if len(parts) > 1 and parts[1] else "Không có mô tả"
        color_str = parts[2] if len(parts) > 2 else None

        # Xác định màu sắc (mặc định là màu Discord)
        color = 0x5865F2
        if color_str:
            color_str = color_str.lstrip('#')  # bỏ dấu # nếu có
            try:
                color = int(color_str, 16)
            except ValueError:
                await ctx.send("⚠️ Mã màu không hợp lệ! Hãy dùng mã hex như `#ff5733`.")
                return

        # Tạo và gửi embed
        embed = nextcord.Embed(
            title=title,
            description=description,
            color=color
        )
        embed.set_footer(
            text=f"Được yêu cầu bởi {ctx.author.display_name}",
            icon_url=ctx.author.display_avatar.url
        )

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"❌ Đã xảy ra lỗi khi tạo embed: {e}")

# --- XỬ LÝ LỖI (ERROR HANDLING CẬP NHẬT) ---
@bot_info.error
@bat_cong_dong.error
@tat_cong_dong.error
@tao_kenh.error
@sua_kenh.error
@xoa_kenh.error
@di_chuyen.error
@sap_xep.error
@tao_role.error
@sua_role.error
@xoa_role.error
@gan_role.error
@go_role.error
@kick.error
@ban.error
@timeout.error
@xoa_tin.error
@server_info.error
@doi_ten.error
@xoa_ten.error
@kenh_info.error
@user_info.error
@create_server.error
@backup_config.error
@restore_config.error
@thiet_lap_chao_mung.error
@export_log_zip.error
@import_log_zip.error
@sao_chep_kenh.error
@che_do_cham.error
@sao_chep_vai_tro.error
@hien_thi_quyen.error
@set_quyen.error
@ping.error
@tu_dong_xoa.error
@anon.error
@xem_nhatky.error
@tinh_trang.error
@bat_xac_minh.error
@poll.error
@gui_nhung.error
async def channel_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Bạn không có quyền `Quản lý kênh` để dùng lệnh này!")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            f"⚠️ **Thiếu đối số! Hướng dẫn nhanh:**\n"
            f"• Tạo: `!tao_kenh [text/voice/forum] [an/hien] [Tên Kênh]`\n"
            f"• Sắp xếp: `!sap_xep [Tên Danh Mục] [#kênh1] [#kênh2]...`"
        )
    elif isinstance(error, commands.ChannelNotFound):
        await ctx.send("❌ Định dạng kênh không đúng. Hãy gắn thẻ kênh bằng dấu `#`.")
    else:
        await ctx.send(f"❌ Lỗi hệ thống: {error}")

bot.run(os.getenv("TOKEN_BOT"))