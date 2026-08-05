from __future__ import annotations

from typing import Any


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

    utilization = pool.get("utilization")
    if not isinstance(utilization, (int, float)) or utilization >= 0.60:
        return current
    depth = max(0, int(send_queue.get("depth_live", send_queue.get("depth", 0)) or 0))
    max_depth = max(1, int(send_queue.get("max_depth") or 1))
    if active >= current and depth < max_depth / 2:
        return min(maximum, current + 1)
    return current
