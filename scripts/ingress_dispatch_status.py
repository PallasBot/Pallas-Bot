#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pallas.console.cli.unified_lifecycle import read_listen_port  # noqa: E402


def fmt_optional(value: float | None, *, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value:.2f}{suffix}"


def fetch_live_dispatch_metrics(
    *,
    port: int,
    opener=urlopen,
) -> dict[str, Any]:
    url = f"http://127.0.0.1:{port}/pallas/api/ingress-dispatch"
    with opener(url, timeout=3.0) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("统一运行时未返回有效 ingress 指标")
    data = payload.get("data")
    if payload.get("ok") is not True or not isinstance(data, dict):
        raise ValueError("统一运行时未返回有效 ingress 指标")
    return data


def main() -> int:
    try:
        data = fetch_live_dispatch_metrics(port=read_listen_port())
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError) as err:
        print(f"读取统一运行时 ingress 指标失败: {err}", file=sys.stderr)
        return 1
    alerts = data.get("alerts") or []
    send_queue = data.get("send_queue") or {}
    pool = data.get("pool_budget") or {}

    print(f"day_key                  {data.get('day_key')}")
    print(
        f"群消息                   {data.get('group_messages', 0)}  "
        f"命令={data.get('command_traffic', 0)}  闲聊={data.get('chatter_traffic', 0)}"
    )
    print(
        f"matcher 考虑/选中/运行    {data.get('matchers_considered', 0)} / "
        f"{data.get('matchers_selected', 0)} / {data.get('matchers_run', 0)}  "
        f"选中率={data.get('matchers_selected_ratio')}"
    )
    print(
        f"ingress P95              {fmt_optional(data.get('ingress_duration_ms_p95'), suffix='ms')}  "
        f"lane 等待均值={fmt_optional(data.get('lane_wait_ms_avg'), suffix='ms')}  "
        f"lane 忙={data.get('lane_busy', 0)}"
    )
    print(
        f"过载信号                 {data.get('overload_signals', 0)}  "
        f"prefetch 跳过={data.get('prefetch_paused', 0)}  "
        f"预处理丢弃={data.get('preprocessor_dropped', 0)}"
    )
    print(
        f"send_queue               depth={send_queue.get('depth_live', send_queue.get('depth', 0))}/"
        f"{send_queue.get('max_depth', '—')}  "
        f"sent={send_queue.get('sent', 0)}  dropped={send_queue.get('dropped', 0)}"
    )
    util = pool.get("utilization")
    util_text = f"{util * 100:.1f}%" if isinstance(util, float) else "—"
    print(f"PG 池利用率              {util_text}  capacity={pool.get('capacity', '—')}")
    hotpath = data.get("hotpath") or {}
    print(
        f"hotpath 路由/分词/查库P95 {fmt_optional(hotpath.get('route_ms_p95'), suffix='ms')} / "
        f"{fmt_optional(hotpath.get('keywords_ms_p95'), suffix='ms')} / "
        f"{fmt_optional(hotpath.get('bundle_ms_p95'), suffix='ms')}"
    )
    print(
        f"hotpath bundle 阶段P95   db={fmt_optional(hotpath.get('db_find_ms_p95'), suffix='ms')}  "
        f"persona={fmt_optional(hotpath.get('persona_ms_p95'), suffix='ms')}  "
        f"affect={fmt_optional(hotpath.get('affect_ms_p95'), suffix='ms')}  "
        f"ban={fmt_optional(hotpath.get('ban_ms_p95'), suffix='ms')}  "
        f"feedback={fmt_optional(hotpath.get('feedback_ms_p95'), suffix='ms')}  "
        f"select={fmt_optional(hotpath.get('select_ms_p95'), suffix='ms')}"
    )
    print(
        f"hotpath SQL 分段P95      total={fmt_optional(hotpath.get('sql_total_ms_p95'), suffix='ms')}  "
        f"ctx={fmt_optional(hotpath.get('sql_context_ms_p95'), suffix='ms')}  "
        f"ban={fmt_optional(hotpath.get('sql_ban_ms_p95'), suffix='ms')}  "
        f"ans={fmt_optional(hotpath.get('sql_answer_ms_p95'), suffix='ms')}  "
        f"msg={fmt_optional(hotpath.get('sql_message_ms_p95'), suffix='ms')}  "
        f"uncached={hotpath.get('reply_query_uncached', 0)}"
    )
    print(
        f"hotpath bundle 缓存命中   {hotpath.get('bundle_cache_hit_ratio', '—')}  "
        f"(+{hotpath.get('bundle_cache_hit', 0)}/-{hotpath.get('bundle_cache_negative_hit', 0)})  "
        f"timeout={hotpath.get('bundle_timeout', 0)}  "
        f"found={hotpath.get('bundle_found', 0)}  none={hotpath.get('bundle_none', 0)}"
    )
    print(
        f"hotpath snapshot/阶段    snap={hotpath.get('reply_snapshot_hit_ratio', '—')}  "
        f"(hit={hotpath.get('reply_snapshot_hit', 0)} miss={hotpath.get('reply_snapshot_miss', 0)} "
        f"skip={hotpath.get('reply_snapshot_skip', 0)})  "
        f"db_miss={hotpath.get('bundle_stage_db_miss', 0)}  "
        f"db_hit={hotpath.get('bundle_stage_db_hit', 0)}  "
        f"no_cand={hotpath.get('bundle_stage_no_candidates', 0)}  "
        f"stage_found={hotpath.get('bundle_stage_found', 0)}"
    )
    print(
        f"hotpath learn            enq={hotpath.get('learn_enqueued', 0)}  "
        f"skip_pressure={hotpath.get('learn_skipped_pressure', 0)}  "
        f"done={hotpath.get('learn_completed', 0)}  "
        f"shed={hotpath.get('chat_shed_sidework', 0)}  "
        f"local_reply={hotpath.get('reply_local_dispatched', 0)}"
    )
    print(
        f"hotpath 分词 LRU          hit={hotpath.get('keywords_lru_hit_ratio', '—')}  "
        f"size={hotpath.get('keywords_lru_size', 0)}"
    )
    if alerts:
        print(f"告警                     {', '.join(str(x) for x in alerts)}")
    else:
        print("告警                     无")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
