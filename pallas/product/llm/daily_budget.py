"""跨进程按天持久化的每日预算计数（供 LLM 任务调用数 / 提供方花费封顶复用）。

计数按天分桶，落在 ``plugin_data_dir("pb_webui")`` 下的 JSON 文件，重启不丢。
每个计数桶可同时累计 calls / tokens / cost 三类数值，按 ``key`` 区分维度
（如任务名、提供方 id）。写入为 best-effort，失败仅告警不阻断主流程。

读写都在线程锁 + 跨进程文件锁内进行：分片部署下 hub/worker 并发 bump 时
不会互相覆盖整文件更新。
"""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nonebot import logger

from pallas.core.foundation.fs_lock import interprocess_file_lock
from pallas.core.foundation.paths import plugin_data_dir

if TYPE_CHECKING:
    from collections.abc import Iterator

_thread_locks: dict[str, threading.RLock] = {}


def _budget_path(name: str) -> Path:
    return plugin_data_dir("pb_webui", create=True) / f"{name}_budget.json"


def _budget_lock_path(name: str) -> Path:
    return _budget_path(name).with_suffix(".lock")


def _thread_lock(name: str) -> threading.RLock:
    lock = _thread_locks.get(name)
    if lock is None:
        lock = threading.RLock()
        _thread_locks[name] = lock
    return lock


@contextmanager
def _budget_lock(name: str) -> Iterator[None]:
    with _thread_lock(name), interprocess_file_lock(_budget_lock_path(name)):
        yield


def _state(name: str) -> dict[str, Any]:
    try:
        raw = json.loads(_budget_path(name).read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _save(name: str, state: dict[str, Any]) -> None:
    try:
        tmp = _budget_path(name).with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        Path(tmp).replace(_budget_path(name))
    except Exception as exc:
        logger.warning("记录每日预算失败 [{}]：{}", name, exc)


def _bucket(state: dict[str, Any], day_key: int, key: str) -> dict[str, float]:
    day = state.get(str(day_key))
    if isinstance(day, dict):
        bucket = day.get(key)
        if isinstance(bucket, dict):
            return {str(k): float(v or 0.0) for k, v in bucket.items()}
    return {}


def used_today(name: str, *, key: str = "", day_key: int | None = None) -> dict[str, float]:
    """今日某 key 的累计计数，返回 ``{"calls":..,"tokens":..,"cost":..}``。"""
    if day_key is None:
        day_key = int(time.time() // 86400)
    with _budget_lock(name):
        bucket = _bucket(_state(name), day_key, key)
    return {
        "calls": float(bucket.get("calls") or 0.0),
        "tokens": float(bucket.get("tokens") or 0.0),
        "cost": float(bucket.get("cost") or 0.0),
    }


def bump_today(
    name: str,
    *,
    key: str = "",
    calls: float = 0.0,
    tokens: float = 0.0,
    cost: float = 0.0,
) -> None:
    """累加今日某 key 的计数（calls/tokens/cost 可分别传）。"""
    if calls <= 0 and tokens <= 0 and cost <= 0:
        return
    day_key = int(time.time() // 86400)
    with _budget_lock(name):
        state = _state(name)
        day = state.get(str(day_key))
        if not isinstance(day, dict):
            day = {}
            state[str(day_key)] = day
        bucket = _bucket(state, day_key, key)
        bucket["calls"] = float(bucket.get("calls") or 0.0) + max(0.0, calls)
        bucket["tokens"] = float(bucket.get("tokens") or 0.0) + max(0.0, tokens)
        bucket["cost"] = float(bucket.get("cost") or 0.0) + max(0.0, cost)
        day[key] = bucket
        _save(name, state)


def reserve_today(name: str, *, key: str = "", count: int = 1, limit: int = 0) -> bool:
    """原子预占今日某 key 的 ``count`` 次调用；超过 ``limit`` 返回 False（0=不限制）。

    预占与检查在同一把锁内完成，供「先占后调」的调用方（如记忆图谱抽取）
    避免并发下多个进程同时通过检查导致超限。
    """
    count = max(1, int(count))
    if limit <= 0:
        return True
    day_key = int(time.time() // 86400)
    with _budget_lock(name):
        state = _state(name)
        day = state.get(str(day_key))
        if not isinstance(day, dict):
            day = {}
            state[str(day_key)] = day
        bucket = _bucket(state, day_key, key)
        used = float(bucket.get("calls") or 0.0)
        if used + count > limit:
            return False
        bucket["calls"] = used + count
        day[key] = bucket
        _save(name, state)
        return True
