"""复读候选查找的限时包装，避免热群拖垮事件循环。"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from nonebot import logger

from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.core.foundation.db.pool_budget import is_pg_pool_timeout_error
from pallas.core.platform.ingress.hotpath_metrics import record_bundle_lookup

from .bundle_cache import (
    lookup_cached_reply_bundle,
    reply_bundle_cache_key,
    store_cached_reply_bundle,
    store_cached_reply_miss,
)

if TYPE_CHECKING:
    from .model import Chat


_inflight_bundle_lookups: dict[str, asyncio.Task[Any]] = {}


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
    data = chat.chat_data
    group_id = int(data.group_id)
    bot_id = int(data.bot_id)
    raw_message = str(data.raw_message or "")
    keywords = str(getattr(data, "keywords", "") or "")
    started = time.perf_counter()

    hit, negative, cached = lookup_cached_reply_bundle(group_id, bot_id, raw_message, keywords)
    if hit:
        record_bundle_lookup(
            duration_ms=(time.perf_counter() - started) * 1000.0,
            cache_hit=True,
            found=not negative,
            negative_hit=negative,
        )
        return None if negative else cached

    timeout = repeater_bundle_timeout_sec()
    lookup_key = reply_bundle_cache_key(group_id, bot_id, raw_message, keywords)
    task = _inflight_bundle_lookups.get(lookup_key)
    if task is None:
        task = asyncio.create_task(
            _find_reply_bundle(chat, limit_sec=timeout),
            name=f"repeater_bundle_lookup:{group_id}:{bot_id}",
        )
        _inflight_bundle_lookups[lookup_key] = task
        task.add_done_callback(lambda completed: _discard_inflight_bundle_lookup(lookup_key, completed))
    try:
        bundle = await asyncio.shield(task)
    except TimeoutError:
        record_bundle_lookup(
            duration_ms=(time.perf_counter() - started) * 1000.0,
            cache_hit=False,
            error="timeout",
        )
        # 超时也短负缓存，避免热群连环打满 PG
        store_cached_reply_miss(group_id, bot_id, raw_message, keywords)
        logger.debug(
            "repeater.find_reply_bundle timeout bot={} group={} limit_sec={}",
            bot_id,
            group_id,
            timeout,
        )
        return None
    except Exception as exc:
        error = "db_timeout" if is_pg_pool_timeout_error(exc) else "other"
        record_bundle_lookup(
            duration_ms=(time.perf_counter() - started) * 1000.0,
            cache_hit=False,
            error=error,
        )
        if is_pg_pool_timeout_error(exc):
            store_cached_reply_miss(group_id, bot_id, raw_message, keywords)
            logger.debug(
                "repeater.find_reply_bundle db_timeout bot={} group={}",
                bot_id,
                group_id,
            )
        else:
            logger.debug(
                "repeater.find_reply_bundle failed bot={} group={}: {}",
                bot_id,
                group_id,
                exc,
            )
        return None

    found = bundle is not None
    record_bundle_lookup(
        duration_ms=(time.perf_counter() - started) * 1000.0,
        cache_hit=False,
        found=found,
    )
    if found:
        store_cached_reply_bundle(group_id, bot_id, raw_message, keywords, bundle)
    else:
        store_cached_reply_miss(group_id, bot_id, raw_message, keywords)
    return bundle


async def _find_reply_bundle(chat: Chat, *, limit_sec: float) -> Any | None:
    if limit_sec <= 0:
        return await chat.find_reply_bundle()
    return await asyncio.wait_for(chat.find_reply_bundle(), timeout=limit_sec)


def _discard_inflight_bundle_lookup(lookup_key: str, completed: asyncio.Task[Any]) -> None:
    if _inflight_bundle_lookups.get(lookup_key) is completed:
        _inflight_bundle_lookups.pop(lookup_key, None)
