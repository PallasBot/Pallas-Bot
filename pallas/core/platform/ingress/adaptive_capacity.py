from __future__ import annotations

from typing import Any


def _downstream_has_capacity(pool: dict[str, Any], send_queue: dict[str, Any]) -> bool:
    utilization = pool.get("utilization")
    if not isinstance(utilization, (int, float)) or utilization >= 0.60:
        return False
    depth = max(0, int(send_queue.get("depth_live", send_queue.get("depth", 0)) or 0))
    max_depth = max(1, int(send_queue.get("max_depth") or 1))
    return depth < max_depth / 2


def adaptive_scheduler_target(
    *,
    current: int,
    baseline: int,
    maximum: int,
    scheduler: dict[str, Any],
    pool: dict[str, Any],
    send_queue: dict[str, Any],
) -> int:
    """在下游有余量时逐步扩大群会话调度并发。"""
    baseline = max(1, int(baseline))
    maximum = max(baseline, int(maximum))
    current = min(maximum, max(baseline, int(current)))
    pending = max(0, int(scheduler.get("pending") or 0))
    active = max(0, int(scheduler.get("active") or 0))

    if pending == 0:
        return baseline

    if not _downstream_has_capacity(pool, send_queue):
        return current
    if active >= current:
        return min(maximum, current + 1)
    return current


def adaptive_chat_lane_target(
    *,
    current: int,
    baseline: int,
    maximum: int,
    scheduler: dict[str, Any],
    chat_lane: dict[str, Any],
    pool: dict[str, Any],
    send_queue: dict[str, Any],
) -> int:
    """只在 chat lane 饱和且下游空闲时逐步扩大实际执行能力。"""
    baseline = max(1, int(baseline))
    maximum = max(baseline, int(maximum))
    current = min(maximum, max(baseline, int(current)))
    pending = max(0, int(scheduler.get("pending") or 0))
    if pending == 0 or not _downstream_has_capacity(pool, send_queue):
        return baseline
    in_use = max(0, int(chat_lane.get("in_use") or 0))
    limit = max(1, int(chat_lane.get("limit") or current))
    if in_use >= limit:
        return min(maximum, current + 1)
    return current
