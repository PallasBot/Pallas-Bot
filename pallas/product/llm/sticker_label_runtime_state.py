"""表情视觉标签任务的跨进程运行状态。"""

from __future__ import annotations

import time
from math import ceil
from typing import Any

from pallas.core.platform.shard.coord.coord_redis_store import (
    coord_key,
    delete_key_sync,
    mutate_json_sync,
    read_json_sync,
)

STICKER_LABEL_PAUSE_TTL_SEC = 365 * 24 * 60 * 60
_PAUSE_KEY = coord_key("llm", "sticker-label-pause")
_CIRCUIT_KEY = coord_key("llm", "sticker-label-circuit")
_local_state: dict[str, object] = {"paused": False, "failures": 0, "circuit_until": 0.0}


def sticker_label_runtime_redis_key() -> str:
    return _CIRCUIT_KEY


def _pause_ttl(_state: dict[str, Any]) -> int:
    return STICKER_LABEL_PAUSE_TTL_SEC


def _state() -> dict[str, object]:
    circuit = read_json_sync(_CIRCUIT_KEY)
    pause = read_json_sync(_PAUSE_KEY)
    if circuit is None and pause is None:
        return _local_state
    return {
        "paused": bool((pause or {}).get("paused")),
        "failures": int((circuit or {}).get("failures") or 0),
        "circuit_until": float((circuit or {}).get("circuit_until") or 0),
    }


def snapshot() -> dict[str, object]:
    state = _state()
    return {
        "paused": bool(state.get("paused")),
        "failures": max(0, int(state.get("failures") or 0)),
        "circuit_until": max(0.0, float(state.get("circuit_until") or 0)),
    }


def lazy_sticker_labels_paused() -> bool:
    return bool(snapshot()["paused"])


def set_lazy_sticker_labels_paused(paused: bool) -> bool:
    desired = bool(paused)

    def update(state: dict[str, Any]) -> None:
        state["paused"] = desired

    shared = mutate_json_sync(_PAUSE_KEY, update, ttl_sec_fn=_pause_ttl)
    if shared is None:
        _local_state["paused"] = desired
    return desired


def sticker_label_circuit_open(*, now: float | None = None) -> bool:
    current = time.time() if now is None else now
    return current < float(snapshot()["circuit_until"])


def sticker_label_circuit_record(
    success: bool,
    *,
    failure_threshold: int,
    cooldown_sec: float,
    now: float | None = None,
) -> None:
    current = time.time() if now is None else now

    def update(state: dict[str, Any]) -> None:
        if success:
            state["failures"] = 0
            state["circuit_until"] = 0.0
            return
        failures = max(0, int(state.get("failures") or 0)) + 1
        state["failures"] = failures
        if failures >= failure_threshold:
            state["circuit_until"] = current + max(0.0, cooldown_sec)

    def circuit_ttl(state: dict[str, Any]) -> int:
        until = float(state.get("circuit_until") or 0)
        return max(60, int(ceil(until - current)) + 1) if until > current else 60

    shared = mutate_json_sync(_CIRCUIT_KEY, update, ttl_sec_fn=circuit_ttl)
    if shared is None:
        update(_local_state)


def reset_sticker_label_runtime_state_for_tests() -> None:
    _local_state.update({"paused": False, "failures": 0, "circuit_until": 0.0})
    delete_key_sync(_PAUSE_KEY)
    delete_key_sync(_CIRCUIT_KEY)
