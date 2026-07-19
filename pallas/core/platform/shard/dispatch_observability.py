from __future__ import annotations

from typing import Any

from pallas.core.platform.shard import context as shard_ctx


def aggregate_ingress_dispatch() -> dict[str, Any]:
    from pallas.core.platform.ingress.dispatch_metrics import dispatch_metrics_snapshot, merge_dispatch_metrics

    if not shard_ctx.sharding_active():
        return {**dispatch_metrics_snapshot(), "sharded": False, "workers": []}

    from pallas.core.platform.bot_runtime.roles import is_hub_role

    if not is_hub_role():
        return {**dispatch_metrics_snapshot(), "sharded": True, "workers": []}

    from pallas.core.platform.shard.console_stats import (
        WORKER_STATS_ACTIVE_SEC,
        iter_worker_shard_ids,
        read_worker_stats_file,
    )
    from pallas.core.platform.shard.observability import pg_pool_estimate

    workers: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for shard_id in iter_worker_shard_ids(max_stale_sec=WORKER_STATS_ACTIVE_SEC):
        blob = read_worker_stats_file(shard_id)
        dispatch = blob.get("ingress_dispatch")
        if isinstance(dispatch, dict):
            rows.append(dispatch)
        workers.append({
            "shard_id": int(shard_id),
            "updated_at": blob.get("updated_at"),
            "ingress_dispatch": dispatch if isinstance(dispatch, dict) else {},
        })

    merged = merge_dispatch_metrics(rows) if rows else dispatch_metrics_snapshot()
    pool = dict(merged.get("pool_budget") or {})
    pool["cluster_pg"] = pg_pool_estimate()
    merged["pool_budget"] = pool
    merged["sharded"] = True
    merged["workers"] = workers
    return merged
