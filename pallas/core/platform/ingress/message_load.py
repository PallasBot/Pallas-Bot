from __future__ import annotations

import contextvars
import time

_OVERLOAD_UNTIL = 0.0
_LAST_ACTIVITY = time.monotonic()
_LANE_WAIT_OVERLOAD_MS = 250
# 阈值属低频变化配置，秒级缓存避免每 matcher 匹配反复读盘（repo_env_raw_value→4 stat）
_LANE_WAIT_OVERLOAD_CACHE_TTL_SEC = 5.0
_lane_wait_overload_cache: int | None = None
_lane_wait_overload_cached_at: float = 0.0
# 本条事件在过载时选择「降质接话」而非整段丢弃闲聊
_CHAT_DEGRADED = contextvars.ContextVar("ingress_chat_degraded", default=False)


def mark_activity() -> None:
    global _LAST_ACTIVITY
    _LAST_ACTIVITY = time.monotonic()


def idle_seconds() -> float:
    return max(0.0, time.monotonic() - _LAST_ACTIVITY)


def signal_overload(duration: float = 5.0) -> None:
    global _OVERLOAD_UNTIL
    if duration <= 0:
        return
    until = time.monotonic() + duration
    if until > _OVERLOAD_UNTIL:
        _OVERLOAD_UNTIL = until
        from pallas.core.platform.ingress.dispatch_metrics import record_overload_signal

        record_overload_signal()


def is_overloaded() -> bool:
    return time.monotonic() < _OVERLOAD_UNTIL


def should_pause_tasks() -> bool:
    return is_overloaded()


def mark_chat_degraded(enabled: bool = True) -> contextvars.Token[bool]:
    return _CHAT_DEGRADED.set(bool(enabled))


def reset_chat_degraded(token: contextvars.Token[bool]) -> None:
    _CHAT_DEGRADED.reset(token)


def is_chat_degraded() -> bool:
    return bool(_CHAT_DEGRADED.get())


def should_shed_chat_sidework() -> bool:
    """过载或本条已标记降质时：停 learn / LLM 锦上添花，仍可本地接话。"""
    return is_overloaded() or is_chat_degraded()


def lane_wait_overload_threshold_ms() -> int:
    global _lane_wait_overload_cache, _lane_wait_overload_cached_at
    now = time.monotonic()
    if (
        _lane_wait_overload_cache is not None
        and now - _lane_wait_overload_cached_at < _LANE_WAIT_OVERLOAD_CACHE_TTL_SEC
    ):
        return _lane_wait_overload_cache

    from pallas.core.foundation.config.repo_settings import repo_env_raw_value

    raw = repo_env_raw_value("PALLAS_LANE_WAIT_OVERLOAD_MS")
    if raw is None:
        value: int = _LANE_WAIT_OVERLOAD_MS
    else:
        try:
            value = max(50, int(str(raw).strip()))
        except ValueError:
            value = _LANE_WAIT_OVERLOAD_MS
    _lane_wait_overload_cache = value
    _lane_wait_overload_cached_at = now
    return value


def record_lane_wait(wait_ms: float, *, busy: bool = False) -> None:
    if wait_ms >= lane_wait_overload_threshold_ms():
        signal_overload(3.0)
    from pallas.core.platform.ingress.dispatch_metrics import record_lane_wait as record_lane_wait_metric

    record_lane_wait_metric(wait_ms, busy=busy)


def record_send_queue_pressure(depth: int, max_depth: int) -> None:
    if max_depth <= 0:
        return
    if depth >= max(1, int(max_depth * 0.85)):
        signal_overload(2.0)


def reset_message_load_for_tests() -> None:
    global _OVERLOAD_UNTIL, _LAST_ACTIVITY, _lane_wait_overload_cache, _lane_wait_overload_cached_at
    _OVERLOAD_UNTIL = 0.0
    _LAST_ACTIVITY = time.monotonic()
    _lane_wait_overload_cache = None
    _lane_wait_overload_cached_at = 0.0
