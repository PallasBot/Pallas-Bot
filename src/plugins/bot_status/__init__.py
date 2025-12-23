from datetime import datetime

from nonebot import (
    get_driver,
    logger,
    on_command,
    on_notice,
)
from nonebot.adapters.milky import Bot
from nonebot.adapters.milky.event import GroupMessageEvent, MessageEvent, NoticeEvent
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata

from .bot_monitor import (
    get_bot_status_info,
    handle_bot_connect,
    handle_bot_disconnect,
    offline_bots,
)
from .config import plugin_config
from .mail_notifier import handle_test_mail_command, notify_bot_offline

__plugin_meta__ = PluginMetadata(
    name="牛牛状态查询",
    description="查询当前连接的Bot状态，检测Bot离线并发送通知",
    usage="""
牛牛在吗 - 查询当前连接的Bot列表
测试邮件 - 测试邮件发送功能
""",
    type="application",
    homepage="https://github.com/PallasBot",
    supported_adapters={"~milky"},
    extra={
        "version": "2.0.0",
        "menu_data": [
            {
                "func": "查看牛牛在线状况",
                "trigger_method": "on_message",
                "trigger_condition": "牛牛在吗",
                "brief_des": "总计牛牛在线情况",
                "detail_des": "当牛牛离线时发送离线通知邮件给号主与Superuser",
            },
            {
                "func": "发送测试邮件",
                "trigger_method": "on_message",
                "trigger_condition": "测试邮件",
                "brief_des": "发送测试邮件",
                "detail_des": "给配置中的邮箱发送测试邮件",
            },
        ],
        "menu_template": "default",
    },
)


STATUS_COOLDOWN_KEY: str = "bot_status"
offline_notice = on_notice(priority=5, block=False)
bot_status_cmd = on_command("牛牛在吗", permission=SUPERUSER, priority=5, block=True)
test_mail_cmd = on_command("测试邮件", permission=SUPERUSER, priority=5, block=True)

driver = get_driver()


@driver.on_startup
async def startup() -> None:
    logger.info("Bot_status is running")


@driver.on_bot_connect
async def _(bot: Bot) -> None:
    await handle_bot_connect(bot)


@driver.on_bot_disconnect
async def _(bot: Bot) -> None:
    await handle_bot_disconnect(bot)


@offline_notice.handle()
async def handle_bot_offline_events(event: NoticeEvent):
    """协议端离线事件"""
    bot_id = 0
    offline_message = ""
    source = ""

    if event.event_type == "bot_offline":
        bot_id = int(event.get_user_id())
        offline_message = event.data.get("reason", "No reason provided")
        source = "napcat_event"
        logger.warning(f"Bot {bot_id} offline: {offline_message}")

    if bot_id and source:
        from .bot_monitor import get_bot_nickname

        # 先尝试获取昵称，如果获取不到再检查offline_bots
        try:
            nickname = await get_bot_nickname(bot_id)
        except Exception:
            # 如果无法获取昵称，检查offline_bots中是否已有信息
            if bot_id in offline_bots and "nickname" in offline_bots[bot_id]:
                nickname = offline_bots[bot_id]["nickname"]
            else:
                nickname = "Unknown Nickname"

        # 标记离线事件防止重复处理
        offline_bots[bot_id] = {
            "nickname": nickname,
            "offline_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": source,
        }

        # 发送离线通知
        await notify_bot_offline(bot_id, nickname, offline_message)


@test_mail_cmd.handle()
async def _(bot: Bot, event: MessageEvent) -> None:
    """测试邮件"""
    await handle_test_mail_command(bot, event)


@bot_status_cmd.handle()
async def handle_bot_status(bot: Bot, event: MessageEvent) -> None:
    """处理状态查询命令"""
    from src.common.config import GroupConfig

    if isinstance(event, GroupMessageEvent):
        config = GroupConfig(group_id=event.data.peer_id, cooldown=10)
        if not await config.is_cooldown(STATUS_COOLDOWN_KEY):
            return
        await config.refresh_cooldown(STATUS_COOLDOWN_KEY)

    # 获取牛牛状态信息
    online_bots, offline_bots_filtered = await get_bot_status_info()

    # 显示在线牛牛
    online_info: str = ""
    online_count: int = len(online_bots)
    if online_bots:
        bot_info_list: list[str] = [f"{nickname} ({bot_id})" for bot_id, nickname in online_bots.items()]
        online_info = f"在线的牛牛 (Total: {online_count}):\n" + "\n".join(bot_info_list)
    else:
        online_info = ""

    # 显示离线牛牛
    offline_info: str = ""
    offline_count: int = len(offline_bots_filtered)
    if offline_bots_filtered:
        offline_list: list[str] = [f"{nickname} ({bot_id})" for bot_id, nickname in offline_bots_filtered.items()]
        offline_info = f"\n\n离线的牛牛 (Total: {offline_count}):\n" + "\n".join(offline_list)

    if offline_info:
        message: str = online_info + offline_info
    else:
        message = online_info

    await bot_status_cmd.finish(message)
