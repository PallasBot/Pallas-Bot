"""分片 worker 计量回灌：从本分片 stats 文件恢复当日计数。"""

from __future__ import annotations

from typing import Any


def load_worker_day_metric(*, metric_key: str, day_key: str) -> dict[str, Any] | None:
    """读取本 worker stats 中与 day_key 匹配的计量块；非 worker 或失败返回 None。"""
    try:
        from pallas.core.platform.shard import context as shard_ctx

        if not (shard_ctx.sharding_active() and shard_ctx.is_worker()):
            return None
        from pallas.core.platform.shard.console_stats import read_worker_stats_file

        blob = read_worker_stats_file(int(shard_ctx.shard_id()))
    except Exception:
        return None
    raw = blob.get(metric_key) if isinstance(blob, dict) else None
    if not isinstance(raw, dict):
        return None
    if str(raw.get("day_key") or "").strip()[:10] != str(day_key or "").strip()[:10]:
        return None
    return raw
