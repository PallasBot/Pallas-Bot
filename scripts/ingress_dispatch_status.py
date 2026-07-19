#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pallas.core.platform.ingress.dispatch_metrics import dispatch_metrics_snapshot  # noqa: E402


def fmt_optional(value: float | None, *, suffix: str = "") -> str:
    if value is None:
        return "—"
    return f"{value:.2f}{suffix}"


def main() -> int:
    data = dispatch_metrics_snapshot()
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
    if alerts:
        print(f"告警                     {', '.join(str(x) for x in alerts)}")
    else:
        print("告警                     无")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
