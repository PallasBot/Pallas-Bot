from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def load_json_file(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if isinstance(raw, dict):
            return raw
    return {}


def save_json_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            fp.write(payload)
        Path(tmp_path).replace(path)
    except Exception:
        try:
            Path(tmp_path).unlink()
        except OSError:
            pass
        raise


def merge_write_bot_nested_entries(path: Path, current_data: dict[str, Any], bot_key: str) -> None:
    merged = load_json_file(path)
    bot_value = current_data.get(bot_key)
    if isinstance(bot_value, dict) and bot_value:
        merged[bot_key] = bot_value
    else:
        merged.pop(bot_key, None)
    save_json_file(path, merged)


def merge_write_bot_entry(path: Path, current_data: dict[str, Any], bot_key: str) -> None:
    merged = load_json_file(path)
    bot_value = current_data.get(bot_key)
    if isinstance(bot_value, dict) and bot_value:
        merged[bot_key] = bot_value
    else:
        merged.pop(bot_key, None)
    save_json_file(path, merged)
