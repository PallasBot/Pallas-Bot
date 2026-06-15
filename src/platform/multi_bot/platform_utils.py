"""出站 Bot 选择：仅 OneBot V11 协议端，多连接时不猜测。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot import get_bots
from nonebot.log import logger

if TYPE_CHECKING:
    from nonebot.adapters import Bot
    from nonebot.adapters.onebot.v11 import Bot as OneBotV11Bot


def list_onebot_v11_bots() -> list[OneBotV11Bot]:
    from nonebot.adapters.onebot.v11 import Bot as V11Bot

    return [bot for bot in get_bots().values() if isinstance(bot, V11Bot)]


def resolve_unique_onebot_v11_bot(log_tag: str = "platform_utils") -> OneBotV11Bot | None:
    """未指定 Bot 时：仅当恰好一只 OneBot V11 在线则自动选用，否则跳过。"""
    bots = list_onebot_v11_bots()
    if not bots:
        logger.warning("platform_utils: 无可用 OneBot V11 连接，已跳过 ({})", log_tag)
        return None
    if len(bots) == 1:
        if len(get_bots()) > 1:
            logger.warning(
                "platform_utils: 多 Bot 在线且未指定，自动选用 OneBot {} ({})",
                bots[0].self_id,
                log_tag,
            )
        return bots[0]
    logger.warning(
        "platform_utils: 存在 {} 只 OneBot V11，无法安全自动选择，已跳过 ({})",
        len(bots),
        log_tag,
    )
    return None


def resolve_onebot_v11_bot(bot: Bot | None = None, bot_id: str | int | None = None, log_tag: str = "") -> Bot | None:
    if bot is not None:
        return bot
    if bot_id is not None:
        key = str(bot_id).strip()
        if key:
            try:
                return get_bots()[key]
            except KeyError:
                logger.warning("platform_utils: Bot {} 未连接 ({})", key, log_tag or "resolve")
                return None
    return resolve_unique_onebot_v11_bot(log_tag or "resolve")


def pick_connected_bot_id(candidates: list[int] | frozenset[int], log_tag: str = "") -> int | None:
    """从候选 QQ 中选取本进程已连接的一只；唯一候选直接返回，多个则保持 fail-open 随机由调用方决定。"""
    connected = {int(k) for k in get_bots().keys() if str(k).isdigit()}
    ready = [int(bid) for bid in candidates if int(bid) in connected]
    if not ready:
        return None
    if len(ready) == 1:
        return ready[0]
    if log_tag:
        logger.debug(
            "platform_utils: 候选牛 {} 中有 {} 只在线，未指定主持牛 ({})",
            len(candidates),
            len(ready),
            log_tag,
        )
    return None
