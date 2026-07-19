"""本机语料 backfill 游标落盘。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_BACKFILL_PATH = Path("data/pallas_config/corpus_backfill.json")


def load_backfill_state() -> dict[str, Any]:
    if not _BACKFILL_PATH.is_file():
        return {}
    try:
        raw = json.loads(_BACKFILL_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(raw) if isinstance(raw, dict) else {}


def save_backfill_state(state: dict[str, Any]) -> None:
    _BACKFILL_PATH.parent.mkdir(parents=True, exist_ok=True)
    _BACKFILL_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
