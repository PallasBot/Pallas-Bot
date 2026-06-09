"""分片集群可观测性聚合（hub 读 worker stats + 本地 coord 扫描）。"""

from __future__ import annotations

from typing import Any

from src.platform.shard.coord_pending import coord_pending_snapshot_sync
from src.platform.shard.ingress_metrics import merge_ingress_metrics
from src.platform.shard.registry.config import is_sharding_active
from src.platform.shard.registry.store import get_shard_registry
from src.platform.shard.repeater_ingress_metrics import merge_repeater_ingress_metrics


def pg_pool_estimate() -> dict[str, Any]:
    from src.foundation.config.repo_settings import repo_env_raw_value

    def cfg(key: str, default: str) -> int:
        raw = repo_env_raw_value(key)
        try:
            return int(str(raw if raw is not None else default).strip())
        except ValueError:
            return int(default)

    pool_size = cfg("PG_POOL_SIZE", "10")
    max_overflow = cfg("PG_MAX_OVERFLOW", "20")
    per_process_max = pool_size + max_overflow
    recommended_per_process = 32
    peak_warn_threshold = 500
    worker_count = 0
    if is_sharding_active():
        reg = get_shard_registry()
        worker_count = len(reg.shards)
        process_count = worker_count + 1  # workers + hub
    else:
        process_count = 1
    peak = per_process_max * process_count
    warning = None
    if per_process_max > recommended_per_process or peak > peak_warn_threshold:
        warning = (
            f"PG 连接池偏大：单进程最多 {per_process_max}，"
            f"约 {process_count} 进程峰值 {peak}；"
            f"建议单进程 pool+overflow ≤ {recommended_per_process}，"
            "并核对 PostgreSQL max_connections"
        )
    return {
        "pg_pool_size": pool_size,
        "pg_max_overflow": max_overflow,
        "per_process_max": per_process_max,
        "recommended_per_process_max": recommended_per_process,
        "worker_shards": worker_count,
        "estimated_processes": process_count,
        "estimated_pg_connections_peak": peak,
        "warning": warning,
    }


def log_pg_pool_warning_if_needed() -> None:
    from nonebot import logger

    info = pg_pool_estimate()
    msg = info.get("warning")
    if msg:
        logger.debug(msg)


def aggregate_shard_observability() -> dict[str, Any]:
    from src.platform.shard.ingress_metrics import ingress_metrics_snapshot
    from src.platform.shard.repeater_ingress_metrics import repeater_ingress_metrics_snapshot

    if not is_sharding_active():
        snap = ingress_metrics_snapshot()
        repeater_snap = repeater_ingress_metrics_snapshot()
        return {
            "sharded": False,
            "ingress_cluster": snap,
            "ingress_process": snap,
            "repeater_ingress_cluster": repeater_snap,
            "repeater_ingress_process": repeater_snap,
            "coord_pending_live": coord_pending_snapshot_sync(),
            "workers": [],
            "pg_pool": pg_pool_estimate(),
        }

    from src.platform.shard.console_stats import iter_worker_shard_ids, read_worker_stats_file

    workers: list[dict[str, Any]] = []
    ingress_rows: list[dict[str, Any]] = []
    repeater_rows: list[dict[str, Any]] = []
    for shard_id in iter_worker_shard_ids():
        blob = read_worker_stats_file(shard_id)
        ingress = blob.get("ingress")
        repeater_ingress = blob.get("repeater_ingress")
        if isinstance(ingress, dict):
            ingress_rows.append(ingress)
        if isinstance(repeater_ingress, dict):
            repeater_rows.append(repeater_ingress)
        workers.append({
            "shard_id": int(shard_id),
            "updated_at": blob.get("updated_at"),
            "ingress": ingress if isinstance(ingress, dict) else {},
            "repeater_ingress": repeater_ingress if isinstance(repeater_ingress, dict) else {},
            "coord_pending": blob.get("coord_pending") if isinstance(blob.get("coord_pending"), dict) else {},
            "process_memory": blob.get("process_memory") if isinstance(blob.get("process_memory"), dict) else {},
        })
    coord_live = coord_pending_snapshot_sync()
    return {
        "sharded": is_sharding_active(),
        "ingress_cluster": merge_ingress_metrics(ingress_rows),
        "repeater_ingress_cluster": merge_repeater_ingress_metrics(repeater_rows),
        "coord_pending_live": coord_live,
        "workers": workers,
        "pg_pool": pg_pool_estimate(),
    }
