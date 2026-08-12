"""入站冷启动窗口与积压消息判定。

刚启动时协议端连接后消息集中涌入，而 LLM / 调度尚未预热，容易把启动期的入站
p95 拉高。这里统一提供「冷启动窗口」与「消息积压年龄」的判定，供调度降质、
积压丢弃与并发渐进共用。
"""

from __future__ import annotations

import time

_ready_at: float | None = None


def mark_ingress_ready() -> None:
    global _ready_at
    _ready_at = time.monotonic()


def ingress_uptime_sec() -> float:
    if _ready_at is None:
        return float("inf")
    return time.monotonic() - _ready_at


def in_cold_start_window() -> bool:
    from pallas.core.platform.ingress.dispatch_runtime_config import get_ingress_dispatch_runtime_config

    return ingress_uptime_sec() < get_ingress_dispatch_runtime_config().cold_start_window_sec


def message_age_sec(event) -> float:
    raw = getattr(event, "time", None)
    if not raw:
        return 0.0
    try:
        return max(0.0, time.time() - float(raw))
    except (TypeError, ValueError):
        return 0.0


def stale_message_drop_needed(event) -> bool:
    from pallas.core.platform.ingress.dispatch_runtime_config import get_ingress_dispatch_runtime_config

    threshold = get_ingress_dispatch_runtime_config().stale_message_sec
    return threshold > 0 and message_age_sec(event) >= threshold
