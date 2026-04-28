import asyncio
import random
from datetime import datetime

from nonebot import (
    get_bots,
    get_driver,
    logger,
    on_command,
    on_notice,
)
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent, NoticeEvent
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata

from src.common.config import BotConfig

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
牛牛报数 - 让当前群内在线牛牛随机报数
测试邮件 - 测试邮件发送功能
""",
    type="application",
    homepage="https://github.com/PallasBot",
    supported_adapters={"~onebot.v11"},
    extra={
        "version": "3.0.0",
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
            {
                "func": "牛牛依次报数",
                "trigger_method": "on_message",
                "trigger_condition": "牛牛报数",
                "brief_des": "在线牛牛依次报数",
                "detail_des": "仅当前群内在线 Bot 参与，随机顺序在群内轮流报数",
            },
        ],
        "menu_template": "default",
    },
)


async def _is_bot_admin(bot: Bot, event: MessageEvent) -> bool:
    try:
        return await BotConfig(int(bot.self_id)).is_admin_of_bot(int(event.get_user_id()))
    except Exception:
        return False


STATUS_COOLDOWN_KEY: str = "bot_status"
COUNT_COOLDOWN_KEY: str = "bot_count"
offline_notice = on_notice(priority=5, block=False)
bot_status_cmd = on_command("牛牛在吗", permission=_is_bot_admin, priority=5, block=True)
bot_count_cmd = on_command("牛牛报数", aliases={"牛牛出列"}, priority=5, block=True)
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

    if event.notice_type == "bot_offline":  # NapCat
        bot_id = event.user_id
        offline_message = getattr(event, "message", "")
        source = "napcat_event"
        logger.warning(f"NapCat Bot {bot_id} offline: {offline_message}")

    elif hasattr(event, "sub_type") and event.sub_type == "BotOfflineEvent":  # Lagrange
        bot_id = getattr(event, "self_id", getattr(event, "user_id", 0))
        offline_message = "Bot Offline"
        source = "lagrange_event"
        logger.warning(f"Lagrange Bot {bot_id} offline")

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
        config = GroupConfig(group_id=event.group_id, cooldown=10)
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


@bot_count_cmd.handle()
async def handle_bot_count(bot: Bot, event: MessageEvent) -> None:
    """处理牛牛报数命令"""
    from src.common.config import GroupConfig

    if not isinstance(event, GroupMessageEvent):
        await bot_count_cmd.finish("牛牛报数仅支持群聊中使用")

    config = GroupConfig(group_id=event.group_id, cooldown=10)
    if not await config.is_cooldown(COUNT_COOLDOWN_KEY):
        return
    await config.refresh_cooldown(COUNT_COOLDOWN_KEY)

    online_bots, _ = await get_bot_status_info()

    current_bots = get_bots()
    group_bot_ids: list[int] = []
    for bot_id in online_bots:
        bot_key = str(bot_id)
        if bot_key not in current_bots:
            continue
        bot_instance = current_bots[bot_key]
        try:
            await bot_instance.get_group_member_info(
                group_id=event.group_id,
                user_id=int(bot_id),
                no_cache=True,
            )
            group_bot_ids.append(bot_id)
        except Exception:
            continue

    if not group_bot_ids:
        return

    seed_text = f"{datetime.now().strftime('%Y-%m-%d')}:{event.group_id}"
    random.Random(seed_text).shuffle(group_bot_ids)
    failed_bots: list[int] = []

    for index, bot_id in enumerate(group_bot_ids, start=1):
        bot_instance = current_bots[str(bot_id)]
        try:
            await bot_instance.send_group_msg(group_id=event.group_id, message=str(f"牛牛{index}号报到！"))
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.warning(f"Bot {bot_id} failed to count in group {event.group_id}: {e}")
            failed_bots.append(bot_id)

    if failed_bots:
        failed_text = "、".join(online_bots.get(bot_id, str(bot_id)) for bot_id in failed_bots)
        await bot_count_cmd.finish(f"报数完成，以下牛牛没能报数：{failed_text}")

    await bot_count_cmd.finish("牛牛们报数完毕！")
