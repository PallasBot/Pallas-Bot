"""协议端 accounts.json 只读快照（hub WebUI 展示昵称等）。"""

from __future__ import annotations

import json

from src.common.paths import plugin_data_dir

_cached_mtime: float | None = None
_cached_names: dict[str, str] | None = None


def protocol_account_display_names() -> dict[str, str]:
    global _cached_mtime, _cached_names
    path = plugin_data_dir("pallas_protocol") / "accounts.json"
    if not path.is_file():
        return {}
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    if _cached_names is not None and _cached_mtime == mtime:
        return dict(_cached_names)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, item in raw.items():
        if not isinstance(item, dict):
            continue
        qq = str(item.get("qq") or item.get("id") or key).strip()
        if not qq.isdigit():
            continue
        disp = str(item.get("display_name") or item.get("nickname") or "").strip()
        if disp:
            out[qq] = disp
    _cached_mtime = mtime
    _cached_names = dict(out)
    return out


def clear_protocol_account_display_names_cache() -> None:
    global _cached_mtime, _cached_names
    _cached_mtime = None
    _cached_names = None
