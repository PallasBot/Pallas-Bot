from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import TYPE_CHECKING, Any

from pallas.core.foundation.command_prefix import matches_command_prefix
from pallas.core.platform.ingress.dream_host_gate import DREAM_HOST_GATE_PLUGIN
from pallas.core.platform.ingress.hosted_activity_gate import (
    loaded_hosted_activity_specs,
    spec_matches_in_room_command,
    spec_matches_speak_traffic,
)
from pallas.core.platform.multi_bot.dedup import needs_group_host_bot_gate
from pallas.core.platform.shard.coord.group_gate import read_owned_gate_bot_id_sync
from pallas.core.platform.shard.coord.hosted_activity_coord import hosted_activity_live

if TYPE_CHECKING:
    from collections.abc import Callable

GATE_EXECUTOR_THREAD_PREFIX = "pallas-ingress-gate"
_GATE_WORKERS = 4

_executor: ThreadPoolExecutor | None = None


def gate_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=_GATE_WORKERS,
            thread_name_prefix=GATE_EXECUTOR_THREAD_PREFIX,
        )
    return _executor


async def run_gate_blocking[T](func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """在 gate 专用池执行同步判定；语义同 ``asyncio.to_thread``，但不与默认 executor（DB / 文件）抢线程。

    Redis 协调判定必须离开事件循环；``to_thread`` 用的是默认池，PG 抖动时这里会排在队尾，
    单独一条通道能让入站请求的 p99 不再跟着 DB 一起抖。
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(gate_executor(), partial(func, *args, **kwargs))


def shutdown_gate_executor() -> None:
    """停机时丢弃排队任务；在途任务不等待，避免拖住 NoneBot 关闭。"""
    global _executor
    executor = _executor
    _executor = None
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)


def ingress_once_claim_safe_before_host_gates(
    group_id: int,
    plain: str,
    *,
    at_fleet_bot: bool,
) -> bool:
    if not needs_group_host_bot_gate():
        return True

    gid = int(group_id)
    text = (plain or "").strip()
    for spec in loaded_hosted_activity_specs():
        in_room = spec_matches_in_room_command(spec, plain)
        speak = spec_matches_speak_traffic(spec, gid, plain, at_fleet_bot=at_fleet_bot)
        open_or_end = any(matches_command_prefix(text, prefix) for prefix in spec.always_pass_prefixes)
        if not in_room and not speak and not open_or_end:
            continue
        if hosted_activity_live(
            activity_namespace=spec.activity_namespace,
            plugin_key=spec.plugin_key,
            group_id=gid,
        ):
            return False

    if read_owned_gate_bot_id_sync(DREAM_HOST_GATE_PLUGIN, gid) is not None:
        return False
    return True
