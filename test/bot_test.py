import nextcord
from nextcord.ext import commands
import os
from dotenv import load_dotenv

load_dotenv()

intents = nextcord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True 

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"🤖 Bot Quản Trị Kênh Nâng Cấp Đã Sẵn Sàng: {bot.user}")


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
@bot.command(name="tao_server")
async def tao_server(ctx, loai_mau: str = "gaming", *, ten_server: str):
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ Bạn phải là Quản trị viên (Administrator) mới được dùng lệnh này!")
        return

    # Sử dụng chính xác mã template Gaming của bạn
    ma_template_gaming = "6cfHZFDdJPjY"
    
    # Chuẩn hóa loại mẫu người dùng gõ
    loai_nhap = loai_mau.lower()

    # Kiểm tra xem người dùng muốn tạo mẫu gì
    if loai_nhap in ["gaming", "game", "trò-chơi"]:
        link_chuan = f"https://discord.new/{ma_template_gaming}"
        
        giao_dien = (
            f"👑 **THIẾT LẬP MÁY CHỦ GAMING ĐÃ SẴN SÀNG**\n"
            f"Bot đã cấu hình xong mẫu thiết kế theo yêu cầu của bạn:\n\n"
            f"👉 **[BẤM VÀO ĐÂY ĐỂ KHỞI TẠO MÁY CHỦ]({link_chuan})**\n\n"
            f"📝 **Hướng dẫn 2 bước thực hiện khi cửa sổ hiện ra:**\n"
            f"1️⃣ Tại ô **TÊN MÁY CHỦ (SERVER NAME)**: Bạn hãy copy và dán chính xác tên này vào: `{ten_server}`\n"
            f"2️⃣ Nhấn nút **Tạo (Create)** ở góc dưới để hoàn tất và nhận ngay quyền Chủ Server!"
        )
    else:
        # Nếu người dùng gõ loại khác (ví dụ: học-tập, clb...) mà bạn chưa có mã
        giao_dien = (
            f"⚠️ Hiện tại Bot mới chỉ hỗ trợ mẫu `gaming` thông qua mã cá nhân của bạn.\n"
            f"Mặc định Bot sẽ cung cấp mẫu Gaming cho tên server: **{ten_server}**\n\n"
            f"👉 **[Bấm vào đây để tạo mẫu Gaming của bạn](https://discord.new/{ma_template_gaming})**\n"
            f"*(Đừng quên đổi tên thành `{ten_server}` trước khi bấm nút Tạo nhé!)*"
        )

    await ctx.send(giao_dien)

# --- XỬ LÝ LỖI (ERROR HANDLING CẬP NHẬT) ---
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
@tao_server.error
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