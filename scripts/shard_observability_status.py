#!/usr/bin/env python3
"""分片可观测摘要（供 run_sharded_bot.sh status 等运维输出）。"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.platform.shard.observability import aggregate_shard_observability  # noqa: E402
from src.platform.shard.registry.config import is_sharding_active  # noqa: E402


def observability_sharded(data: dict) -> bool:
    if data.get("sharded"):
        return True
    if is_sharding_active():
        return True
    workers = data.get("workers")
    return isinstance(workers, list) and len(workers) > 0


def fmt_rate(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def main() -> int:
    data = aggregate_shard_observability()
    if not observability_sharded(data):
        print("未启用分片（unified 模式）")
        return 0

    ing = data.get("ingress_cluster") or {}
    coord = data.get("coord_pending_live") or {}
    pg = data.get("pg_pool") or {}
    workers = data.get("workers") or []

    print(
        f"ingress 命中率(集群/今日)  {fmt_rate(ing.get('claim_hit_rate'))}  "
        f"won={ing.get('claim_won', 0)} lost={ing.get('claim_lost', 0)}"
    )
    print(
        f"ingress 事件              {ing.get('events', 0)}  "
        f"fanout跳过={ing.get('fanout_bypass', 0)}  "
        f"早丢弃={int(ing.get('early_fleet', 0)) + int(ing.get('early_not_at_target', 0))}"
    )
    print(
        f"coord Redis              keys={coord.get('total_json', 0)}  "
        f"actionable={coord.get('actionable_total', coord.get('bot_action_open', 0))}  "
        f"historical={coord.get('historical_retained', 0)}  "
        f"bot_action_open={coord.get('bot_action_open', 0)}  "
        f"stale_open={coord.get('bot_action_stale_open', 0)}"
    )
    if coord.get("scan_skipped"):
        print("coord live scan          skipped（默认不扫 Redis，全量排查用 prune_shard_coord.py --live-scan）")
    ba = (coord.get("by_dir") or {}).get("bot_action", 0)
    if ba:
        print(f"coord bot_action 键       {ba}  （prune_shard_coord.py 仅输出快照）")

    peak = pg.get("estimated_pg_connections_peak")
    proc = pg.get("estimated_processes")
    per = pg.get("per_process_max")
    print(f"PG 连接池(估)             峰值 {peak}  ({proc} 进程 × {per})")
    warning = pg.get("warning")
    if warning:
        print(f"PG 警告                   {warning}")

    if workers:
        with_stats = sum(1 for w in workers if isinstance(w, dict) and w.get("ingress"))
        print(f"worker stats 落盘         {with_stats}/{len(workers)}")
        for row in workers:
            if not isinstance(row, dict):
                continue
            sid = row.get("shard_id")
            sub = row.get("ingress") or {}
            if not sub:
                print(f"  worker-{sid}              （尚无 ingress 统计，重启 worker 后等待群消息）")
                continue
            print(
                f"  worker-{sid}              命中率 {fmt_rate(sub.get('claim_hit_rate'))}  "
                f"won={sub.get('claim_won', 0)} lost={sub.get('claim_lost', 0)}"
            )
    else:
        print("worker stats 落盘         0（worker 未运行或尚未刷盘）")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
