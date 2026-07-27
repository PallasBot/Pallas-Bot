"""LLM 任务按自然日汇总持久化（Bot / AI 快照）。"""

from __future__ import annotations

import json
import os
import threading
from datetime import date, timedelta
from operator import itemgetter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

_STORE_VER = 1
_MAX_RETAIN_DAYS = 500
_LOCK = threading.RLock()


def stats_file_path() -> Path:
    from pallas.core.foundation.paths import plugin_data_dir

    return plugin_data_dir("pb_webui", create=True) / "llm_daily_stats.json"


def _read_raw() -> dict[str, Any]:
    p = stats_file_path()
    if not p.exists():
        return {"v": _STORE_VER, "by_day": {}}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"v": _STORE_VER, "by_day": {}}
    if not isinstance(raw, dict):
        return {"v": _STORE_VER, "by_day": {}}
    raw.setdefault("v", _STORE_VER)
    bd = raw.get("by_day")
    if not isinstance(bd, dict):
        raw["by_day"] = {}
    return raw


def _atomic_write(data: dict[str, Any]) -> None:
    p = stats_file_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    try:
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(p)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _trim_old_days(by_day: dict[str, Any]) -> None:
    keys = sorted(k for k in by_day if isinstance(k, str) and len(k) >= 10)
    if len(keys) <= _MAX_RETAIN_DAYS:
        return
    for k in keys[: len(keys) - _MAX_RETAIN_DAYS]:
        by_day.pop(k, None)


def _metric_weight(key: str, value: object) -> int:
    if not isinstance(value, dict):
        return 0
    if key in {"rag", "memory_rag"}:
        return int(value.get("hit_count") or 0) + int(value.get("miss_count") or 0)
    if key == "tokens":
        total = int(value.get("total_tokens") or 0)
        if total > 0:
            return total
        return int(value.get("prompt_tokens") or 0) + int(value.get("completion_tokens") or 0)
    if key in {"provider_stats", "model_stats"}:
        total = 0
        for row in value.values():
            if isinstance(row, dict):
                total += int(row.get("requests") or 0)
        return total
    if key == "images":
        return int(value.get("ok_count") or 0) + int(value.get("fail_count") or 0) + int(value.get("image_count") or 0)
    if key == "gates":
        return int(value.get("skip") or 0) + int(value.get("defer") or 0) + int(value.get("proceed") or 0)
    if key == "totals":
        return sum(int(v or 0) for v in value.values() if not isinstance(v, dict))
    if key == "by_task":
        total = 0
        for metrics in value.values():
            if not isinstance(metrics, dict):
                continue
            for name, count in metrics.items():
                if name == "route_counts" and isinstance(count, dict):
                    total += sum(int(v or 0) for v in count.values())
                else:
                    try:
                        total += int(count or 0)
                    except (TypeError, ValueError):
                        pass
        return total
    return 0


def _merge_dimension_prefer_max(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    out = {str(k): dict(v) for k, v in existing.items() if isinstance(v, dict)}
    for key, row in incoming.items():
        if not isinstance(row, dict):
            continue
        name = str(key or "").strip()
        if not name:
            continue
        cur = out.get(name)
        if not cur:
            out[name] = dict(row)
            continue
        if int(row.get("requests") or 0) >= int(cur.get("requests") or 0):
            out[name] = dict(row)
    return out


def _merge_int_map_prefer_max(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    keys = set(existing) | set(incoming)
    for key in keys:
        name = str(key or "").strip()
        if not name:
            continue
        try:
            a = int(existing.get(key) or 0)
        except (TypeError, ValueError):
            a = 0
        try:
            b = int(incoming.get(key) or 0)
        except (TypeError, ValueError):
            b = 0
        out[name] = max(a, b)
    return out


def _merge_by_task_prefer_max(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    keys = set(existing) | set(incoming)
    for key in keys:
        name = str(key or "").strip()
        if not name:
            continue
        prev = existing.get(key) if isinstance(existing.get(key), dict) else {}
        nxt = incoming.get(key) if isinstance(incoming.get(key), dict) else {}
        row: dict[str, Any] = {}
        metric_keys = set(prev) | set(nxt)
        for metric in metric_keys:
            if metric == "route_counts":
                continue
            try:
                a = int(prev.get(metric) or 0)
            except (TypeError, ValueError):
                a = 0
            try:
                b = int(nxt.get(metric) or 0)
            except (TypeError, ValueError):
                b = 0
            row[metric] = max(a, b)
        prev_routes = prev.get("route_counts") if isinstance(prev.get("route_counts"), dict) else {}
        nxt_routes = nxt.get("route_counts") if isinstance(nxt.get("route_counts"), dict) else {}
        if prev_routes or nxt_routes:
            row["route_counts"] = _merge_int_map_prefer_max(prev_routes, nxt_routes)
        out[name] = row
    return out


def _prefer_complete_metric(key: str, existing: Any, incoming: Any) -> Any:
    """累计型指标：禁止用偏少快照覆盖（重启后实时内存变小）。"""
    if not isinstance(incoming, dict):
        return existing if existing is not None else incoming
    if not isinstance(existing, dict):
        return incoming
    if key in {"provider_stats", "model_stats"}:
        return _merge_dimension_prefer_max(existing, incoming)
    if key == "by_task":
        return _merge_by_task_prefer_max(existing, incoming)
    if key in {"totals", "gates"}:
        return _merge_int_map_prefer_max(existing, incoming)
    w_ex = _metric_weight(key, existing)
    w_in = _metric_weight(key, incoming)
    if w_in > w_ex:
        return incoming
    if w_in < w_ex:
        return existing
    # 同量级保留已有（避免 hit/miss 分别取 max 把总量抬高）
    return existing


_PREFER_COMPLETE_KEYS = frozenset({
    "tokens",
    "images",
    "provider_stats",
    "model_stats",
    "rag",
    "memory_rag",
    "by_task",
    "totals",
    "gates",
})


def merge_side_snapshot(existing: dict[str, Any] | None, snapshot: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return existing if isinstance(existing, dict) else {}
    out = dict(existing) if isinstance(existing, dict) else {}
    for key in (
        "source",
        "day_key",
        "updated_at",
        "by_task",
        "totals",
        "tokens",
        "images",
        "classification",
        "reachable",
        "provider_stats",
        "model_stats",
        "failure_counts",
        "state_counts",
        "rag",
        "memory_rag",
        "gates",
    ):
        if key not in snapshot:
            continue
        if key in _PREFER_COMPLETE_KEYS and key in out:
            out[key] = _prefer_complete_metric(key, out.get(key), snapshot.get(key))
        else:
            out[key] = snapshot[key]
    return out


def write_day_side(day: str, side: str, snapshot: dict[str, Any]) -> None:
    """写入某日 Bot 或 AI 侧快照；side 为 bot / ai。"""
    day_key = str(day).strip()[:10]
    side_key = str(side).strip().lower()
    if len(day_key) < 10 or side_key not in {"bot", "ai"}:
        return
    if not isinstance(snapshot, dict):
        return
    with _LOCK:
        data = _read_raw()
        days = data.setdefault("by_day", {})
        if not isinstance(days, dict):
            data["by_day"] = {}
            days = data["by_day"]
        row = days.setdefault(day_key, {})
        if not isinstance(row, dict):
            days[day_key] = {}
            row = days[day_key]
        prev = row.get(side_key) if isinstance(row.get(side_key), dict) else None
        merged = merge_side_snapshot(prev, snapshot)
        if prev == merged:
            return
        row[side_key] = merged
        _trim_old_days(days)
        _atomic_write(data)


def _parse_iso_day(s: str) -> date | None:
    try:
        return date.fromisoformat(str(s).strip()[:10])
    except ValueError:
        return None


def load_range(*, start_day: str, end_day: str) -> tuple[list[dict[str, Any]], str, str]:
    sd = _parse_iso_day(start_day)
    ed = _parse_iso_day(end_day)
    if sd is None or ed is None:
        return [], start_day[:10], end_day[:10]
    if sd > ed:
        sd, ed = ed, sd
    start_eff = sd.isoformat()
    end_eff = ed.isoformat()
    with _LOCK:
        data = _read_raw()
        days = data.get("by_day")
        if not isinstance(days, dict):
            return [], start_eff, end_eff
    rows: list[dict[str, Any]] = []
    cur = sd
    while cur <= ed:
        key = cur.isoformat()
        day_row = days.get(key) if isinstance(days, dict) else None
        if isinstance(day_row, dict):
            bot = day_row.get("bot") if isinstance(day_row.get("bot"), dict) else None
            ai = day_row.get("ai") if isinstance(day_row.get("ai"), dict) else None
            if bot or ai:
                rows.append({
                    "date": key,
                    "bot": bot,
                    "ai": ai,
                })
        cur += timedelta(days=1)
    rows.sort(key=itemgetter("date"))
    return rows, start_eff, end_eff
