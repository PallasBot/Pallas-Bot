"""控制台元信息，供 api / extended_api 共用，避免循环导入。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

_CONSOLE_EXTRA: dict[str, Any] = {}


def set_console_meta(d: dict[str, Any] | None) -> None:
    _CONSOLE_EXTRA.clear()
    if d:
        _CONSOLE_EXTRA.update(d)


def patch_console_meta(**kwargs: Any) -> None:
    _CONSOLE_EXTRA.update(kwargs)


def get_console_meta() -> dict[str, Any]:
    return dict(_CONSOLE_EXTRA)


def merge_console_version_from_disk(meta: dict[str, Any], static_root: Path | None) -> None:
    if not static_root or not static_root.is_dir():
        return
    version_file = static_root / "console-version.json"
    if not version_file.is_file():
        return
    try:
        data = json.loads(version_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        for key in ("version", "commit", "build_time"):
            val = str(data.get(key, "") or "").strip()
            if val:
                meta[key] = val
            elif key in meta:
                del meta[key]
    except Exception:
        pass
