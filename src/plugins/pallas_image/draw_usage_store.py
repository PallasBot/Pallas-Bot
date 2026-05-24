from __future__ import annotations

import json
import threading
from datetime import date
from typing import TYPE_CHECKING

from nonebot import logger

if TYPE_CHECKING:
    from pathlib import Path

from src.common.paths import plugin_data_dir

_USAGE_FILE = "pallas_draw_daily_usage.json"
_VERSION = 1

_lock = threading.Lock()
_pallas_draw_usage: dict[tuple[int, int], tuple[date, int]] = {}


def usage_store_path() -> Path:
    return plugin_data_dir("pallas_image") / _USAGE_FILE


def _key_str(group_id: int, user_id: int) -> str:
    return f"{group_id}:{user_id}"


def _parse_key(s: str) -> tuple[int, int] | None:
    try:
        parts = s.split(":", 1)
        if len(parts) != 2:
            return None
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _parse_entry(v: object) -> tuple[date, int] | None:
    day_s: object
    count_raw: object
    if isinstance(v, dict):
        day_s = v.get("day")
        count_raw = v.get("count")
    elif isinstance(v, list) and len(v) == 2:
        day_s, count_raw = v[0], v[1]
    else:
        return None
    try:
        d = date.fromisoformat(str(day_s))
        c = int(count_raw)
    except (ValueError, TypeError):
        return None
    if c < 0:
        return None
    return d, c


def _load() -> None:
    global _pallas_draw_usage
    path = usage_store_path()
    if not path.is_file():
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"pallas_image draw_usage file invalid, ignored: {e}")
        return
    if not isinstance(raw, dict):
        return
    entries = raw.get("entries")
    if not isinstance(entries, dict):
        return
    out: dict[tuple[int, int], tuple[date, int]] = {}
    for k, v in entries.items():
        parsed_key = _parse_key(str(k))
        if parsed_key is None:
            continue
        parsed_val = _parse_entry(v)
        if parsed_val is None:
            continue
        out[parsed_key] = parsed_val
    _pallas_draw_usage = out
    _prune_stale_memory()


def _prune_stale_memory() -> None:
    global _pallas_draw_usage
    today = date.today()
    _pallas_draw_usage = {k: v for k, v in _pallas_draw_usage.items() if v[0] == today}


def _persist() -> None:
    _prune_stale_memory()
    path = usage_store_path()
    today = date.today()
    entries: dict[str, dict[str, object]] = {}
    for (g, u), (d, c) in _pallas_draw_usage.items():
        if d != today or c <= 0:
            continue
        entries[_key_str(g, u)] = {"day": d.isoformat(), "count": c}
    payload = {"version": _VERSION, "entries": entries}
    _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2))


def pallas_draw_usage_today(usage_key: tuple[int, int]) -> int:
    with _lock:
        today = date.today()
        prev = _pallas_draw_usage.get(usage_key)
        if prev is None or prev[0] != today:
            return 0
        return prev[1]


def bump_pallas_draw_usage(usage_key: tuple[int, int], count_usage: bool) -> None:
    if not count_usage:
        return
    group_id, user_id = usage_key
    with _lock:
        today = date.today()
        prev = _pallas_draw_usage.get(usage_key)
        if prev is None or prev[0] != today:
            new_count = 1
            _pallas_draw_usage[usage_key] = (today, new_count)
        else:
            new_count = prev[1] + 1
            _pallas_draw_usage[usage_key] = (today, new_count)
        try:
            _persist()
        except OSError as e:
            logger.error(f"pallas_image draw_usage persist failed: {e}")
            return
    logger.info(
        f"pallas_image draw usage bumped group={group_id} user={user_id} count={new_count} day={today.isoformat()}",
    )


_load()
