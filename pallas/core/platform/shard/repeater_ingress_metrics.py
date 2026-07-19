from __future__ import annotations

import time
from typing import Any

_COUNTERS = (
    "events",
    "early_worker_gate",
    "early_plugin_disabled",
    "early_plugin_command",
    "early_fanout_bypass",
    "early_message_scrub",
    "early_message_id_dup",
    "early_group_event_dup",
    "early_federate_claim",
    "early_local_claim",
    "early_cross_bot_claim",
    "claim_won",
    "claim_lost",
    "reply_total",
    "reply_mode_normal",
    "reply_mode_god",
    "reply_mode_ghost",
    "reply_source_same_group_recent_live",
    "reply_source_same_group",
    "reply_source_cross_group",
    "reply_recent_hit",
    "reply_repeat_hit",
    "reply_pick_default",
    "reply_pick_god_recent_live",
    "reply_pick_god_pool",
    "reply_pick_ghost_pool",
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
    for key in _COUNTERS:
        _state[key] = 0


def record_repeater_ingress_event() -> None:
    _rollover_if_needed()
    _state["events"] += 1


def record_repeater_ingress_early_discard(reason: str) -> None:
    _rollover_if_needed()
    mapping = {
        "worker_gate": "early_worker_gate",
        "plugin_disabled": "early_plugin_disabled",
        "plugin_command": "early_plugin_command",
        "fanout_bypass": "early_fanout_bypass",
        "message_scrub": "early_message_scrub",
        "message_id_dup": "early_message_id_dup",
        "group_event_dup": "early_group_event_dup",
        "federate_claim": "early_federate_claim",
        "local_claim": "early_local_claim",
        "cross_bot_claim": "early_cross_bot_claim",
    }
    key = mapping.get(reason)
    if key is not None:
        _state[key] += 1


def record_repeater_ingress_claim(*, won: bool) -> None:
    _rollover_if_needed()
    _state["claim_won" if won else "claim_lost"] += 1


def record_repeater_reply_selection(
    *,
    mode: str,
    source: str,
    recent_hit: bool,
    repeat_hit: bool,
    pick_path: str,
) -> None:
    _rollover_if_needed()
    _state["reply_total"] += 1
    mode_key = {
        "normal": "reply_mode_normal",
        "god": "reply_mode_god",
        "ghost": "reply_mode_ghost",
    }.get(str(mode))
    if mode_key is not None:
        _state[mode_key] += 1
    source_key = {
        "same_group_recent_live": "reply_source_same_group_recent_live",
        "same_group": "reply_source_same_group",
        "cross_group": "reply_source_cross_group",
    }.get(str(source))
    if source_key is not None:
        _state[source_key] += 1
    if recent_hit:
        _state["reply_recent_hit"] += 1
    if repeat_hit:
        _state["reply_repeat_hit"] += 1
    pick_key = {
        "default": "reply_pick_default",
        "god_recent_live": "reply_pick_god_recent_live",
        "god_pool": "reply_pick_god_pool",
        "ghost_pool": "reply_pick_ghost_pool",
    }.get(str(pick_path))
    if pick_key is not None:
        _state[pick_key] += 1


def repeater_ingress_metrics_snapshot() -> dict[str, Any]:
    _rollover_if_needed()
    won = int(_state["claim_won"])
    lost = int(_state["claim_lost"])
    attempts = won + lost
    return {
        "day_key": _day_key or _today_key(),
        **{key: int(_state[key]) for key in _COUNTERS},
        "claim_attempts": attempts,
        "claim_hit_rate": round(won / attempts, 4) if attempts else None,
    }


def merge_repeater_ingress_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    merged = dict.fromkeys(_COUNTERS, 0)
    merged["claim_attempts"] = 0
    day_key = ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        day_key = str(row.get("day_key") or day_key)
        for key in _COUNTERS:
            merged[key] += int(row.get(key) or 0)
    won = int(merged["claim_won"])
    lost = int(merged["claim_lost"])
    attempts = won + lost
    merged["day_key"] = day_key
    merged["claim_attempts"] = attempts
    merged["claim_hit_rate"] = round(won / attempts, 4) if attempts else None
    return merged


def clear_repeater_ingress_metrics_for_tests() -> None:
    global _day_key
    _day_key = _today_key()
    for key in _COUNTERS:
        _state[key] = 0
