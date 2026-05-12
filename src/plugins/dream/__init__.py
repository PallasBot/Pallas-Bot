import asyncio
import random
import re

from nonebot import logger, on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, permission
from nonebot.exception import ActionFailed
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from src.common.config import BotConfig, GroupConfig
from src.common.message_scrub import is_message_scrub_blocked_async
from src.common.message_scrub.log_preview import scrub_intercept_log_preview

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
    description=("牛牛的梦话：多群同时做梦时同 Bot 漂流互通，随机间隔推送与复读共用管理员的「不可以」触发梦库删除。"),
    usage="""
指令：
- 牛牛做梦 — 进入做梦（持续约 5～15 分钟；未醉酒时推送梦话间隔约 45～165）
- 牛牛醒梦 / 牛牛别做梦 — 结束本群做梦

做梦中采集群消息入梦库，并向同 Bot 其它正在做梦的群漂流（图/文有上限）。

本群醉酒期间做梦推送间隔全程约 5～20s；首场醉酒另有一次夺舍名片 + 受害者历史句（每场梦最多一次）。
管理员（与复读相同权限）：回复牛牛消息后发送「不可以」，或撤回牛牛消息 — 从梦库删除与所针对内容匹配的记录。
    """.strip(),
    type="application",
    homepage="https://github.com/PallasBot",
    supported_adapters={"~onebot.v11"},
    extra={
        "version": "3.0.0",
        "menu_data": [
            {
                "func": "牛牛做梦",
                "trigger_method": "on_message",
                "trigger_condition": "牛牛做梦",
                "brief_des": "进入做梦漂流状态",
                "detail_des": (
                    "进梦后可收到他群漂流、历史梦（本进程多账号并库抽样）、归档图或已学句；"
                    "同一场内已发正文/图片去重。未醉酒时间隔约 45～165s，醉酒整段约 5～20s。"
                    "默认本会话最多发 3 张图，首场醉酒联动后提升至 5 张。多 Bot 同群时有群级冷却。"
                ),
            },
            {
                "func": "牛牛醒梦",
                "trigger_method": "on_message",
                "trigger_condition": "牛牛醒梦/牛牛别做梦",
                "brief_des": "结束做梦",
                "detail_des": "立即结束本群的做梦状态并停止后台推送；发送「……梦醒了。」。",
            },
            {
                "func": "梦话采集",
                "trigger_method": "on_message",
                "trigger_condition": "本群处于做梦中",
                "brief_des": "群聊写入梦库并可跨群漂流",
                "detail_des": (
                    "做梦期间群友消息异步写入 message（keywords 以 is_dream 为前缀）；"
                    "纯文本与最多 2 张图可随机投递到同 Bot 其它正在做梦的群。"
                    "明文或 raw 含「不可以」时不采集、不漂流。"
                ),
            },
            {
                "func": "做梦×醉酒",
                "trigger_method": "worker",
                "trigger_condition": "本群做梦中且醉酒度>0",
                "brief_des": "醉酒全程短间隔；首场另有一次夺舍与历史一句",
                "detail_des": (
                    "醉酒度>0 时每一轮等待均为约 5～20 秒；"
                    "首场醉酒另有一轮不发常规梦话：尝试与 take_name 醉酒夺舍一致的改名片并 update_taken_name，"
                    "若选中成员再随机发其近 90 天内非梦库纯文本历史一句；本场发图上限 3→5 在该轮后保持。"
                    "牛牛非群管或无可用成员/历史时仍消耗首场夺舍轮。"
                ),
            },
            {
                "func": "梦库清理（不可以）",
                "trigger_method": "on_message",
                "trigger_condition": "回复消息后 @牛牛 发送不可以",
                "brief_des": "按所回复内容删除梦库记录",
                "detail_des": ("与复读「不可以」操作方式相同"),
            },
        ],
        "menu_template": "default",
    },
)


_PLAIN_TRIGGERS = frozenset({"牛牛做梦", "牛牛醒梦", "牛牛别做梦"})
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
    await send_dream_wake_text(event.self_id, event.group_id)


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
    if dream_capture_blocked_by_substrings(plain, event.raw_message):
        return
    norm_raw = re.sub(r"\[CQ:image,[^\]]*\]", "[CQ:image]", event.raw_message)
    if await is_message_scrub_blocked_async(plain_text=plain, raw_message=norm_raw):
        logger.info(
            "message_scrub 已拦截 bot={} group={} user={} msg_id={} plain_preview={}",
            event.self_id,
            event.group_id,
            event.user_id,
            event.message_id,
            scrub_intercept_log_preview(plain, norm_raw),
        )
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
