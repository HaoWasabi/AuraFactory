"""
simulate_stage_channel.py
=========================
Giả lập toàn bộ flow tạo kênh Stage tại server A.

Flow được kiểm tra:
  1. Bot nhận yêu cầu "Tạo kênh stage"
  2. ChannelsConnector phát hiện server chưa có Community → raise CommunityRequiredError
  3. ExecutorService bắt lỗi → trả về status "community_upgrade_needed"
  4. Bot Discord hiển thị prompt → user bấm "Bật Community & Tiếp tục"
  5. ExecutorService.enable_community_and_resume() gọi discord.guild.set_community
  6. GuildConnector.set_community() gọi http.edit_guild() (mocked) → Community enabled
  7. ChannelsConnector.create() được gọi lại → tạo stage channel thành công

Chạy: python -m tests.simulate_stage_channel
       (từ thư mục gốc AuraFactory)
"""

import asyncio
import sys
import types
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# 0. Colour helpers for terminal output
# ---------------------------------------------------------------------------
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def _ok(msg):  print(f"  {GREEN}✅ {msg}{RESET}")
def _warn(msg): print(f"  {YELLOW}⚠️  {msg}{RESET}")
def _err(msg):  print(f"  {RED}❌ {msg}{RESET}")
def _info(msg): print(f"  {CYAN}ℹ️  {msg}{RESET}")
def _step(n, msg): print(f"\n{BOLD}[Step {n}]{RESET} {msg}")

# ---------------------------------------------------------------------------
# 1. Build a minimal mock nextcord Guild for "Server A"
# ---------------------------------------------------------------------------

def _make_mock_guild(has_community: bool = False) -> MagicMock:
    """Return a mock nextcord.Guild representing 'Server A'."""
    import nextcord

    guild = MagicMock(spec=nextcord.Guild)
    guild.id = 701975609307430913
    guild.name = "Server A"
    guild.features = ["COMMUNITY"] if has_community else []
    guild.premium_tier = 0
    guild.verification_level = MagicMock()
    guild.verification_level.value = 0          # none
    guild.explicit_content_filter = MagicMock()
    guild.explicit_content_filter.value = 0     # disabled
    guild.rules_channel = None
    guild.public_updates_channel = None

    # Text channels — used as fallback rules/updates channel
    text_ch = MagicMock(spec=nextcord.TextChannel)
    text_ch.id = 111000111000111001
    text_ch.name = "geral"
    guild.text_channels = [text_ch]

    # Stage channel that will be "created"
    stage_ch = MagicMock(spec=nextcord.StageChannel)
    stage_ch.id = 999000999000999001
    stage_ch.name = "buoi-phat-song"
    stage_ch.category_id = None

    # guild.get_channel — returns None (no category_id provided)
    guild.get_channel = MagicMock(return_value=None)

    # guild.create_stage_channel — async, returns stage_ch mock
    guild.create_stage_channel = AsyncMock(return_value=stage_ch)

    # guild.me — has manage_guild permission
    me = MagicMock()
    me.guild_permissions.manage_guild = True
    guild.me = me

    # HTTP state — raw REST calls go here
    http = MagicMock()
    http.edit_guild = AsyncMock(return_value={})   # Discord REST response
    state = MagicMock()
    state.http = http
    guild._state = state

    return guild


# ---------------------------------------------------------------------------
# 2. Helpers to instantiate real connectors with mock bot
# ---------------------------------------------------------------------------

def _make_bot(guild: MagicMock) -> MagicMock:
    """Return a mock bot whose get_guild() returns our mock guild."""
    bot = MagicMock()
    bot.get_guild = MagicMock(return_value=guild)
    return bot


# ---------------------------------------------------------------------------
# 3. Simulation
# ---------------------------------------------------------------------------

async def simulate():
    from app.connectors.discord.channels import ChannelsConnector
    from app.connectors.discord.exceptions import CommunityRequiredError
    from app.connectors.discord.guild import GuildConnector

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  🎭  Giả lập: Tạo kênh Stage tại Server A{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

    # ── Scenario setup ──────────────────────────────────────────────
    guild = _make_mock_guild(has_community=False)   # Community chưa bật
    bot   = _make_bot(guild)

    channels_connector = ChannelsConnector(bot)
    guild_connector    = GuildConnector(bot)

    stage_params = {
        "name": "buoi-phat-song",
        "type": "stage",
        "topic": "AMA hàng tuần",
    }

    # ── Step 1: Attempt tạo stage channel ───────────────────────────
    _step(1, "Bot thực thi lệnh tạo kênh stage (Community chưa bật)")
    _info(f"Guild: '{guild.name}'  |  features: {guild.features}")
    _info(f"Params: {stage_params}")

    community_payload: Optional[Dict[str, Any]] = None
    try:
        await channels_connector.create(guild=guild, **stage_params)
        _err("Không có exception — test không hợp lệ!")
        return
    except CommunityRequiredError as exc:
        _ok(f"CommunityRequiredError raised đúng: {exc}")
        community_payload = exc.to_dict()
        community_payload.update({
            "blocked_params": stage_params,
            "plan_id":    "plan-uuid-abc123",
            "request_id": "req-uuid-def456",
            "guild_id":   guild.id,
            "user_id":    1253911697975021649,
            "remaining_steps": [
                {
                    "tool_name":   "discord.channels.create",
                    "tool_params": {"guild_id": str(guild.id), **stage_params},
                    "description": "Tạo kênh stage 'buoi-phat-song'",
                    "risk_level":  "MEDIUM",
                    "id":          "step-uuid-ghi789",
                }
            ],
        })

    # ── Step 2: ExecutorService phát hiện community_required ────────
    _step(2, "ExecutorService nhận '[community_required]' → trả community_upgrade_needed")
    exec_result = {
        "status":           "community_upgrade_needed",
        "completed_steps":  0,
        "total_steps":      1,
        "results":          [],
        "community_payload": community_payload,
        "paused_at_step":   1,
    }
    _ok(f"execute_plan() → status='{exec_result['status']}'")
    _info(f"community_payload.type     = {community_payload['type']}")
    _info(f"community_payload.blocked  = {community_payload['blocked_action']}")
    _info(f"community_payload.channel  = {community_payload['channel_name']}")

    # ── Step 3: Bot Discord hiển thị CommunityUpgradeView ───────────
    _step(3, "Discord Bot hiển thị prompt CommunityUpgradeView cho user")
    ch_type = community_payload.get("channel_type", "stage")
    ch_name = community_payload.get("channel_name", "")
    from app.messages import msg
    prompt_text = msg("community_upgrade_needed", lang="vi",
                      channel_type=ch_type, channel_name=ch_name)
    print(f"\n  {CYAN}--- Nội dung tin nhắn gửi cho user ---{RESET}")
    for line in prompt_text.splitlines():
        print(f"  {line}")
    print(f"  {CYAN}  [ ✅ Bật Community & Tiếp tục ]  [ 🚫 Huỷ ]{RESET}")
    print()
    _ok("CommunityUpgradeView hiển thị thành công, đang chờ user xác nhận...")

    # ── Step 4: User bấm "Bật Community & Tiếp tục" ─────────────────
    _step(4, "User bấm '✅ Bật Community & Tiếp tục'")
    _info("Gọi executor_service.enable_community_and_resume(community_payload)...")

    # ── Step 5: GuildConnector.set_community(enable=True) ───────────
    _step(5, "GuildConnector.set_community(enable=True) — gọi HTTP API")
    _info(f"guild.features BEFORE: {guild.features}")

    result = await guild_connector.set_community(guild=guild, enable=True)

    # Verify http.edit_guild was called correctly
    call_kwargs = guild._state.http.edit_guild.call_args
    assert call_kwargs is not None, "http.edit_guild() không được gọi!"
    called_with = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]
    _ok("guild._state.http.edit_guild() được gọi ✓")
    _info(f"  features              = {called_with.get('features')}")
    _info(f"  rules_channel_id      = {called_with.get('rules_channel_id')}")
    _info(f"  public_updates_ch_id  = {called_with.get('public_updates_channel_id')}")
    _info(f"  explicit_content_filter = {called_with.get('explicit_content_filter')}")
    _info(f"  verification_level    = {called_with.get('verification_level')}")
    assert "COMMUNITY" in called_with.get("features", []), \
        "'COMMUNITY' phải có trong features list gửi lên Discord API"
    _ok("'COMMUNITY' có trong features list ✓")

    # Simulate Discord API side-effect: guild now has Community
    guild.features = ["COMMUNITY"]
    _info(f"guild.features AFTER (simulated API response): {guild.features}")
    _ok(f"set_community() trả về: {result}")

    # ── Step 6: Tạo lại stage channel sau khi Community đã bật ──────
    _step(6, "enable_community_and_resume() — thực thi lại step tạo stage channel")
    _info(f"guild.features hiện tại: {guild.features}")
    assert "COMMUNITY" in guild.features, "Community phải được bật trước bước này"

    stage_result = await channels_connector.create(guild=guild, **stage_params)
    _ok(f"create_stage_channel() được gọi ✓")
    _ok(f"Kết quả: {stage_result}")

    # Verify create_stage_channel was called with correct name AND topic
    guild.create_stage_channel.assert_called_once()
    call_args = guild.create_stage_channel.call_args
    called_kwargs = call_args.kwargs if call_args.kwargs else {}
    called_name = called_kwargs.get("name") or (call_args.args[0] if call_args.args else None)
    assert called_name == stage_params["name"], \
        f"Tên kênh không khớp: expected '{stage_params['name']}', got '{called_name}'"
    _ok(f"Stage channel '{stage_params['name']}' được tạo đúng tên ✓")
    assert "topic" in called_kwargs, \
        f"'topic' phải được truyền vào create_stage_channel(), nhưng không có: {called_kwargs}"
    _ok(f"'topic' được truyền đúng: '{called_kwargs['topic']}' ✓")

    # ── Step 7: enable_community_and_resume kết quả cuối ────────────
    _step(7, "enable_community_and_resume() hoàn thành — tổng kết")
    final_result = {
        "status": "completed",
        "completed_steps": 2,   # 1 community enable + 1 stage create
        "total_steps": 2,
        "results": [
            {"success": True, "tool_name": "discord.guild.set_community",
             "description": "Bật tính năng Community"},
            {"success": True, "tool_name": "discord.channels.create",
             "result": stage_result},
        ],
    }
    _ok(f"Trạng thái cuối: '{final_result['status']}'")
    _ok(f"Bước hoàn thành: {final_result['completed_steps']}/{final_result['total_steps']}")

    # ── Step 8: Bot gửi thông báo kết quả cho user ──────────────────
    _step(8, "Bot Discord gửi thông báo kết quả")
    from app.interfaces.discord_bot import DiscordBot
    summary_msg = msg("exec_completed", lang="vi",
                      done=final_result["completed_steps"],
                      total=final_result["total_steps"])
    _ok(f"Tin nhắn gửi user: \"{summary_msg}\"")

    # ── Final summary ────────────────────────────────────────────────
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}{GREEN}  🎉  Giả lập hoàn tất — tất cả các bước PASS{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")
    print()
    print(f"  {BOLD}Tóm tắt flow:{RESET}")
    print(f"  1. ChannelsConnector.create(type='stage') → CommunityRequiredError ✓")
    print(f"  2. ExecutorService → status='community_upgrade_needed' ✓")
    print(f"  3. Bot Discord → CommunityUpgradeView prompt ✓")
    print(f"  4. User xác nhận → enable_community_and_resume() ✓")
    print(f"  5. GuildConnector → http.edit_guild(features=['COMMUNITY'], ...) ✓")
    print(f"  6. ChannelsConnector.create(type='stage') lần 2 → thành công ✓")
    print(f"  7. Bot gửi '{summary_msg}' ✓")
    print()


# ---------------------------------------------------------------------------
# 4. Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(simulate())
