"""OneBot 发消息在进程关闭或 WS 断开时的容错。"""

from __future__ import annotations

import asyncio

from nonebot import logger
from nonebot.adapters.onebot.v11.exception import ApiNotAvailable

BOT_SEND_UNAVAILABLE_ERRORS: tuple[type[BaseException], ...] = (
    ApiNotAvailable,
    asyncio.CancelledError,
)


def is_bot_send_unavailable(exc: BaseException) -> bool:
    return isinstance(exc, BOT_SEND_UNAVAILABLE_ERRORS)


def log_bot_send_unavailable(exc: BaseException, *, context: str, **ident: object) -> None:
    detail = ", ".join(f"{k}={v}" for k, v in ident.items())
    if detail:
        logger.debug("{}: send skipped {} ({})", context, type(exc).__name__, detail)
    else:
        logger.debug("{}: send skipped {}", context, type(exc).__name__)
