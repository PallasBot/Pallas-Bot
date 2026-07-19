"""分片 worker ingress 门控计数。"""

from __future__ import annotations

import time
from typing import Any

from pallas.core.platform.shard import context as shard_ctx

_COUNTERS = (
    "events",
    "early_fleet",
    "early_not_at_target",
    "early_federate",
    "early_spy_host",
    "fanout_bypass",
    "claim_won",
    "claim_lost",
)
_state: dict[str, int] = dict.fromkeys(_COUNTERS, 0)
_day_key = ""


def _today_key() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def _rollover_if_needed() -> None:
    global _day_key
    today = _today_key()
    if _day_key == today:
        return
    _day_key = today
    for k in _COUNTERS:
        _state[k] = 0


def should_record_ingress_metrics(bot_id: int) -> bool:
    """分片 worker 仅代表牛记数；unified 仅最小 QQ 记数，避免多连接重复放大。"""
    from pallas.core.platform.multi_bot.fleet import get_fleet_bot_ids
    from pallas.core.platform.shard.local_representative import is_local_worker_representative

    if not shard_ctx.sharding_active():
        fleet = get_fleet_bot_ids()
        if not fleet:
            return True
        return int(bot_id) == min(int(x) for x in fleet)
    return is_local_worker_representative(bot_id)


def record_ingress_event() -> None:
    _rollover_if_needed()
    _state["events"] += 1


def record_ingress_early_discard(reason: str) -> None:
    _rollover_if_needed()
    if reason == "fleet":
        key = "early_fleet"
    elif reason == "federate":
        key = "early_federate"
    elif reason == "spy_host":
        key = "early_spy_host"
    else:
        key = "early_not_at_target"
    _state[key] += 1


def record_ingress_fanout_bypass() -> None:
    _rollover_if_needed()
    _state["fanout_bypass"] += 1


def record_ingress_claim(*, won: bool) -> None:
    _rollover_if_needed()
    _state["claim_won" if won else "claim_lost"] += 1


def ingress_metrics_snapshot() -> dict[str, Any]:
    _rollover_if_needed()
    won = int(_state["claim_won"])
    lost = int(_state["claim_lost"])
    attempts = won + lost
    return {
        "day_key": _day_key or _today_key(),
        **{k: int(_state[k]) for k in _COUNTERS},
        "claim_attempts": attempts,
        "claim_hit_rate": round(won / attempts, 4) if attempts else None,
    }


def merge_ingress_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    merged = dict.fromkeys(_COUNTERS, 0)
    merged["claim_attempts"] = 0
    day_key = ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        day_key = str(row.get("day_key") or day_key)
        for k in _COUNTERS:
            merged[k] += int(row.get(k) or 0)
    won = int(merged["claim_won"])
    lost = int(merged["claim_lost"])
    attempts = won + lost
    merged["day_key"] = day_key
    merged["claim_attempts"] = attempts
    merged["claim_hit_rate"] = round(won / attempts, 4) if attempts else None
    return merged
