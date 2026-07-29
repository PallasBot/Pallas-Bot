"""复读候选查找的限时包装，避免热群拖垮事件循环。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from nonebot import logger

from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.core.foundation.db.pool_budget import is_pg_pool_timeout_error

if TYPE_CHECKING:
    from .model import Chat


def repeater_bundle_timeout_sec() -> float:
    """查库上限秒数；``0`` 表示不限时。默认 0.8s。"""
    raw = repo_env_raw_value("PALLAS_REPEATER_BUNDLE_TIMEOUT_SEC")
    if raw is None:
        return 0.8
    try:
        return max(0.0, float(str(raw).strip()))
    except ValueError:
        return 0.8


async def find_reply_bundle_bounded(chat: Chat) -> Any | None:
    timeout = repeater_bundle_timeout_sec()
    try:
        if timeout <= 0:
            return await chat.find_reply_bundle()
        return await asyncio.wait_for(chat.find_reply_bundle(), timeout=timeout)
    except TimeoutError:
        logger.debug(
            "repeater.find_reply_bundle timeout bot={} group={} limit_sec={}",
            getattr(chat.chat_data, "bot_id", 0),
            getattr(chat.chat_data, "group_id", 0),
            timeout,
        )
        return None
    except Exception as exc:
        if is_pg_pool_timeout_error(exc):
            logger.debug(
                "repeater.find_reply_bundle db_timeout bot={} group={}",
                getattr(chat.chat_data, "bot_id", 0),
                getattr(chat.chat_data, "group_id", 0),
            )
        else:
            logger.debug(
                "repeater.find_reply_bundle failed bot={} group={}: {}",
                getattr(chat.chat_data, "bot_id", 0),
                getattr(chat.chat_data, "group_id", 0),
                exc,
            )
        return None
