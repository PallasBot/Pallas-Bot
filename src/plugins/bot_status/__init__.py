import asyncio
import contextlib
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
from nonebot.plugin import PluginMetadata

from src.features.cmd_perm import permission_for_command
from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.features.cmd_perm.metadata_text import (
    SCENE_BOTH,
    SCENE_GROUP,
    SCENE_PRIVATE,
    join_usage,
    usage_line,
)
from src.platform.shard.registry.config import is_sharding_active

from .bot_monitor import (
    get_bot_status_info,
    handle_bot_connect,
    handle_bot_disconnect,
    list_connected_bots_in_group,
    offline_bots,
)
from .mail_notifier import handle_test_mail_command, notify_bot_offline

__plugin_meta__ = PluginMetadata(
    name="牛牛状态",
    description="查询牛牛在线状态、群内报数与离线邮件通知。",
    usage=join_usage(
        usage_line("牛牛在吗", "号主查看在线/离线牛牛"),
        usage_line("牛牛报数 / 牛牛出列", "群内在线牛牛依次报到"),
        usage_line("测试邮件", "超管测试 SMTP"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "command_permissions": [
            {"id": "bot_status.status", "label": "牛牛在吗", "default": "bot_moderator"},
            {"id": "bot_status.test_mail", "label": "测试邮件", "default": "superuser"},
            {"id": "bot_status.count", "label": "牛牛报数 / 牛牛出列", "default": "everyone"},
        ],
        "menu_data": [
            {
                "func": "牛牛在吗",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_BOTH,
                "trigger_condition": "牛牛在吗",
                "command_permission": "bot_status.status",
                "brief_des": "查看在线情况",
                "detail_des": (
                    "按 bot_status_list_mode 列出在线/离线（connected=全集群曾连 WS；"
                    "fleet=协议名册；session=本 worker）；离线邮件另有宽限期。"
                ),
            },
            {
                "func": "发送测试邮件",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_PRIVATE,
                "trigger_condition": "测试邮件",
                "command_permission": "bot_status.test_mail",
                "brief_des": "发送测试邮件",
                "detail_des": "给配置中的邮箱发送测试邮件",
            },
            {
                "func": "牛牛依次报数",
                "trigger_method": "on_cmd",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛报数 / 牛牛出列",
                "command_permission": "bot_status.count",
                "brief_des": "在线牛牛依次报数",
                "detail_des": "仅当前群内在线 Bot 参与，随机顺序在群内轮流报数",
            },
        ],
    },
)


STATUS_COOLDOWN_KEY: str = "bot_status"
COUNT_COOLDOWN_KEY: str = "bot_count"
offline_notice = on_notice(priority=5, block=False)
bot_status_cmd = on_command("牛牛在吗", permission=permission_for_command("bot_status.status"), priority=5, block=True)
bot_count_cmd = on_command(
    "牛牛报数", aliases={"牛牛出列"}, priority=5, block=True, permission=permission_for_command("bot_status.count")
)
test_mail_cmd = on_command(
    "测试邮件", permission=permission_for_command("bot_status.test_mail"), priority=5, block=True
)

driver = get_driver()


@driver.on_startup
async def startup() -> None:
    logger.info("Bot_status plugin startup")


@driver.on_bot_connect
async def _(bot: Bot) -> None:
    await handle_bot_connect(bot)


@driver.on_bot_disconnect
async def _(bot: Bot) -> None:
    await handle_bot_disconnect(bot)


@offline_notice.handle()
async def handle_bot_offline_events(event: NoticeEvent):
    """协议端离线事件"""
    if event.notice_type == "group_msg_emoji_like":
        return

    bot_id = 0
    offline_message = ""
    source = ""

    if event.notice_type == "bot_offline":  # NapCat
        bot_id = event.user_id
        offline_message = getattr(event, "message", "")
        source = "napcat_event"
        logger.warning(f"bot [{bot_id}] offline (napcat) message={offline_message!r}")

    elif hasattr(event, "sub_type") and event.sub_type == "BotOfflineEvent":  # Lagrange
        bot_id = getattr(event, "self_id", getattr(event, "user_id", 0))
        offline_message = "Bot Offline"
        source = "lagrange_event"
        logger.warning(f"bot [{bot_id}] offline (lagrange)")

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

        qq = int(bot_id)
        from src.platform.shard.presence import close_local_bot_connection, mark_protocol_bot_offline

        await mark_protocol_bot_offline(qq)
        asyncio.create_task(close_local_bot_connection(qq), name=f"protocol_offline_close_ws:{qq}")

        # 发送离线通知
        await notify_bot_offline(bot_id, nickname, offline_message)


@test_mail_cmd.handle()
async def _(bot: Bot, event: MessageEvent) -> None:
    """测试邮件"""
    await handle_test_mail_command(bot, event)


@bot_status_cmd.handle()
async def handle_bot_status(bot: Bot, event: MessageEvent) -> None:
    """处理状态查询命令"""
    from src.foundation.config import GroupConfig

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
    from src.foundation.config import GroupConfig
    from src.platform.shard.coord.bot_count import STAGGER_SEC, run_shard_coordinated_bot_count

    if not isinstance(event, GroupMessageEvent):
        await bot_count_cmd.finish("牛牛报数仅支持群聊中使用")

    self_id = int(bot.self_id)

    if is_sharding_active():
        from src.platform.shard.coord.bot_count import update_shard_bot_count_registration
        from src.platform.shard.local_representative import is_local_worker_representative
        from src.plugins.duel.duel_bots import list_local_fleet_bots_in_group

        plain = (event.get_plaintext() or "").strip()
        local_ids = [self_id]
        if is_local_worker_representative(self_id):
            probed = await list_local_fleet_bots_in_group(event.group_id)
            local_ids = sorted({self_id, *probed})

        coord_task = asyncio.create_task(
            run_shard_coordinated_bot_count(
                group_id=event.group_id,
                user_id=int(event.user_id),
                plaintext=plain,
                message_time=event.time,
                self_bot_id=self_id,
                local_bot_ids=local_ids,
            )
        )
        try:
            if is_local_worker_representative(self_id) and local_ids:
                await update_shard_bot_count_registration(
                    group_id=event.group_id,
                    user_id=int(event.user_id),
                    plaintext=plain,
                    message_time=event.time,
                    bot_ids=local_ids,
                )
            coord = await coord_task
        except asyncio.CancelledError:
            raise
        finally:
            if not coord_task.done():
                coord_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await coord_task
        if coord is None:
            return
        index, total = coord
        await asyncio.sleep((index - 1) * STAGGER_SEC)
        try:
            await bot.send_group_msg(group_id=event.group_id, message=f"牛牛{index}号报到！")
        except Exception as e:
            logger.warning(f"bot [{self_id}] shard bot_count send failed in group [{event.group_id}]: {e}")
            return
        if index == total:
            await asyncio.sleep(0.3)
            await bot_count_cmd.finish("牛牛们报数完毕！")
        return

    group_bot_ids = await list_connected_bots_in_group(event.group_id)
    if not group_bot_ids:
        return

    config = GroupConfig(group_id=event.group_id, cooldown=10)
    if not await config.is_cooldown(COUNT_COOLDOWN_KEY):
        return
    await config.refresh_cooldown(COUNT_COOLDOWN_KEY)

    seed_text = f"{datetime.now().strftime('%Y-%m-%d')}:{event.group_id}"
    random.Random(seed_text).shuffle(group_bot_ids)
    failed_bots: list[int] = []
    current_bots = get_bots()

    for index, bot_id in enumerate(group_bot_ids, start=1):
        bot_instance = current_bots[str(bot_id)]
        try:
            await bot_instance.send_group_msg(group_id=event.group_id, message=str(f"牛牛{index}号报到！"))
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.warning(f"bot [{bot_id}] bot_count send_group_msg failed in group [{event.group_id}]: {e}")
            failed_bots.append(bot_id)

    if failed_bots:
        online_bots, _ = await get_bot_status_info()
        failed_text = "、".join(online_bots.get(bot_id, str(bot_id)) for bot_id in failed_bots)
        await bot_count_cmd.finish(f"报数完成，以下牛牛没能报数：{failed_text}")

    await bot_count_cmd.finish("牛牛们报数完毕！")
