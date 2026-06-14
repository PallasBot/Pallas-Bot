import asyncio
import random
import re

from nonebot import logger, on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, permission
from nonebot.exception import ActionFailed
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.features.cmd_perm.metadata_text import SCENE_AUTO, SCENE_GROUP, join_usage, usage_line
from src.features.message_scrub import is_message_scrub_blocked_async
from src.features.message_scrub.log_preview import scrub_intercept_log_preview
from src.foundation.config import BotConfig, GroupConfig
from src.platform.ingress.dream_host_gate import dream_session_ingress_passes

from . import ban_handlers as _dream_ban_handlers  # noqa: F401 — 注册梦库「不可以」/撤回清理
from .capture_filter import dream_capture_blocked_by_substrings
from .http_utils import download_image_url
from .payload import DriftPayload
from .runtime import (
    broadcast_drift,
    launch_dream_worker,
    log_dream_chat_to_db,
    send_dream_wake_text,
    stop_dream_worker,
)

__plugin_meta__ = PluginMetadata(
    name="牛牛做梦",
    description="跨群梦话漂流与历史梦推送，醉酒时更密。",
    usage=join_usage(
        usage_line("牛牛做梦", "进入做梦约 5～15 分钟，可收他群漂流"),
        usage_line("牛牛醒梦 / 牛牛别做梦", "结束本群做梦"),
        usage_line("牛牛醒一醒", "醒酒时亦会醒梦"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "command_permissions": [
            {"id": "dream.ban_cleanup", "label": "梦库清理（不可以）", "default": "staff"},
        ],
        "menu_data": [
            {
                "func": "牛牛做梦",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛做梦",
                "brief_des": "进入做梦漂流",
                "detail_des": (
                    "持续约 5～15 分钟；可收到他群漂流、历史梦话或图片。"
                    "未醉酒时梦话间隔较长，醉酒时更密；每场有发图上限。"
                ),
            },
            {
                "func": "牛牛醒梦",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛醒梦 / 牛牛别做梦",
                "brief_des": "结束做梦",
                "detail_des": "立即停止梦话；也可通过「牛牛醒一醒」醒酒时一并结束。",
            },
            {
                "func": "梦话与漂流",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_AUTO,
                "trigger_condition": "本群做梦中",
                "brief_des": "采集群聊并跨群漂流",
                "detail_des": "做梦中群友文字与图片会进入梦库，并可能漂到其它正在做梦的群。",
            },
            {
                "func": "梦库清理",
                "trigger_method": "on_message",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "@牛牛 回复某条消息：不可以",
                "command_permission": "dream.ban_cleanup",
                "brief_des": "删除梦库中匹配内容",
                "detail_des": "与复读「不可以」相同：回复目标消息后 @牛牛 说「不可以」。",
            },
        ],
    },
)


_PLAIN_TRIGGERS = frozenset({"牛牛做梦", "牛牛醒梦", "牛牛别做梦", "牛牛醒一醒", "牛牛别喝了"})
DREAM_GROUP_COOLDOWN_KEY = "dream"
DREAM_GROUP_COOLDOWN_SEC = 10


async def is_dream_start(event: GroupMessageEvent) -> bool:
    return event.get_plaintext().strip() == "牛牛做梦"


dream_start = on_message(
    rule=Rule(is_dream_start),
    priority=5,
    block=True,
    permission=permission.GROUP,
)


@dream_start.handle()
async def _(event: GroupMessageEvent):
    config = BotConfig(event.self_id, event.group_id, cooldown=3)
    if not await config.is_cooldown("dream"):
        return
    group_cfg = GroupConfig(event.group_id, cooldown=DREAM_GROUP_COOLDOWN_SEC)
    if not await group_cfg.is_cooldown(DREAM_GROUP_COOLDOWN_KEY):
        return
    await group_cfg.refresh_cooldown(DREAM_GROUP_COOLDOWN_KEY)
    await config.refresh_cooldown("dream")
    duration = random.randint(300, 900)
    try:
        await dream_start.send("博士，只要相信，梦就会成为现实。")
    except ActionFailed:
        pass
    await launch_dream_worker(event.self_id, event.group_id, duration)
    logger.info(f"bot [{event.self_id}] dream started in group [{event.group_id}] for {duration} sec")


async def is_dream_wake(event: GroupMessageEvent) -> bool:
    if event.get_plaintext().strip() not in {"牛牛醒梦", "牛牛别做梦"}:
        return False
    return await dream_session_ingress_passes(int(event.self_id), int(event.group_id))


dream_wake = on_message(
    rule=Rule(is_dream_wake),
    priority=5,
    block=True,
    permission=permission.GROUP,
)


@dream_wake.handle()
async def _(event: GroupMessageEvent):
    config = BotConfig(event.self_id, event.group_id)
    if not await config.is_dreaming():
        return
    await config.stop_dream()
    await stop_dream_worker(event.self_id, event.group_id)
    await send_dream_wake_text(event.self_id, event.group_id)


async def is_dream_capture(event: GroupMessageEvent) -> bool:
    if event.user_id == event.self_id:
        return False
    cfg = BotConfig(event.self_id, event.group_id)
    if not await cfg.is_dreaming():
        return False
    return await dream_session_ingress_passes(int(event.self_id), int(event.group_id))


dream_capture = on_message(
    rule=Rule(is_dream_capture),
    priority=18,
    block=False,
    permission=permission.GROUP,
)


@dream_capture.handle()
async def _(event: GroupMessageEvent):
    plain = event.get_plaintext().strip()
    if plain in _PLAIN_TRIGGERS:
        return
    if dream_capture_blocked_by_substrings(plain, event.raw_message):
        return
    norm_raw = (
        re.sub(r"\[CQ:image,[^\]]*\]", "[CQ:image]", event.raw_message)
        if "[CQ:image," in event.raw_message
        else event.raw_message
    )
    if await is_message_scrub_blocked_async(plain_text=plain, raw_message=norm_raw):
        pv = scrub_intercept_log_preview(plain, norm_raw)
        logger.info(
            f"bot [{event.self_id}] dream capture skipped (message_scrub) in group [{event.group_id}] "
            f"user [{event.user_id}] msg_id [{event.message_id}] preview [{pv}]"
        )
        return
    nick = (event.sender.card or event.sender.nickname or str(event.user_id)).strip() or str(event.user_id)

    try:
        await log_dream_chat_to_db(event, plain=plain, nick=nick)
    except Exception as e:
        logger.debug(f"bot [{event.self_id}] dream capture db insert failed in group [{event.group_id}]: {e}")

    async def drift_job():
        try:
            img_n = 0
            for seg in event.message:
                if seg.type != "image":
                    continue
                if img_n >= 2:
                    break
                url = (seg.data.get("url") or seg.data.get("file") or "").strip()
                if not url:
                    continue
                data = await download_image_url(url)
                if data:
                    await broadcast_drift(
                        event.self_id,
                        event.group_id,
                        DriftPayload(nickname=nick, image_bytes=data),
                    )
                    img_n += 1
            if plain and len(plain) <= 800:
                await broadcast_drift(event.self_id, event.group_id, DriftPayload(nickname=nick, text=plain))
        except Exception as e:
            logger.debug(f"bot [{event.self_id}] dream capture drift job failed in group [{event.group_id}]: {e}")

    asyncio.create_task(drift_job())
