import asyncio
import random

from nonebot import logger, on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, permission
from nonebot.exception import ActionFailed
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from src.common.config import BotConfig

from .http_utils import download_image_url
from .payload import DriftPayload
from .runtime import (
    broadcast_drift,
    launch_dream_worker,
    log_dream_chat_to_db,
    stop_dream_worker,
)

__plugin_meta__ = PluginMetadata(
    name="牛牛做梦",
    description="牛牛的梦话，来自其他群友的聊天！ 多群同时做梦时联机互传；随机投放梦话！",
    usage="""
牛牛做梦 - 进入做梦状态（跨群漂流瓶式互通，随机间隔推送）
牛牛醒梦 / 牛牛别做梦 - 结束本群做梦
    """.strip(),
    type="application",
    homepage="https://github.com/PallasBot",
    supported_adapters={"~onebot.v11"},
    extra={
        "version": "1.0.0",
        "menu_data": [
            {
                "func": "牛牛做梦",
                "trigger_method": "on_message",
                "trigger_condition": "牛牛做梦",
                "brief_des": "进入做梦漂流状态",
                "detail_des": (
                    "进梦可随机收到库中历史梦记录；多群同时做梦时联机互传。"
                    "间隔随机，会将牛牛画画存的图，其他群友的漂流梦话，或者已经学过的句子，随机投放给群友。"
                ),
            },
            {
                "func": "牛牛醒梦",
                "trigger_method": "on_message",
                "trigger_condition": "牛牛醒梦/牛牛别做梦",
                "brief_des": "结束做梦",
                "detail_des": "立即结束本群的做梦状态。",
            },
        ],
        "menu_template": "default",
    },
)

_PLAIN_TRIGGERS = frozenset({"牛牛做梦", "牛牛醒梦", "牛牛别做梦"})


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
    await config.refresh_cooldown("dream")
    duration = random.randint(300, 900)
    try:
        await dream_start.send("博士，只要相信，梦就会成为现实。")
    except ActionFailed:
        pass
    await launch_dream_worker(event.self_id, event.group_id, duration)
    logger.info("bot [{}] dream started in group [{}] for {}s", event.self_id, event.group_id, duration)


async def is_dream_wake(event: GroupMessageEvent) -> bool:
    return event.get_plaintext().strip() in {"牛牛醒梦", "牛牛别做梦"}


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
    try:
        await dream_wake.send("……梦醒了。")
    except ActionFailed:
        pass


async def is_dream_capture(event: GroupMessageEvent) -> bool:
    if event.user_id == event.self_id:
        return False
    cfg = BotConfig(event.self_id, event.group_id)
    return await cfg.is_dreaming()


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

    async def job():
        try:
            await log_dream_chat_to_db(event)
            nick = (event.sender.card or event.sender.nickname or str(event.user_id)).strip() or str(event.user_id)
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
            logger.debug("dream capture job failed: {}", e)

    asyncio.create_task(job())
