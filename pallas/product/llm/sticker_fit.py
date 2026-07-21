"""表情包 fit 最小闭环：登记、标签匹配、反馈降级。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def default_sticker_fit_path() -> Path:
    import os

    from pallas.core.foundation.paths import plugin_data_dir

    env_dir = str(os.environ.get("PALLAS_DATA_DIR") or "").strip()
    if env_dir:
        root = Path(env_dir) / "llm"
        root.mkdir(parents=True, exist_ok=True)
        return root / "sticker_fit.json"
    path = plugin_data_dir("pb_webui", create=True) / "llm"
    path.mkdir(parents=True, exist_ok=True)
    return path / "sticker_fit.json"


class StickerFitStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_sticker_fit_path()
        self._items: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            self._items = {}
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._items = {}
            return
        rows = payload.get("items") if isinstance(payload, dict) else payload
        items: dict[str, dict[str, Any]] = {}
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                sticker_id = str(row.get("sticker_id") or "").strip()
                if not sticker_id:
                    continue
                items[sticker_id] = _normalize_item(row)
        self._items = items

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"items": list(self._items.values())}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, sticker_id: str) -> dict[str, Any] | None:
        item = self._items.get(str(sticker_id or "").strip())
        return dict(item) if item else None

    def upsert(
        self,
        *,
        sticker_id: str,
        tags: list[str] | None = None,
        persona_fit: bool = True,
    ) -> dict[str, Any]:
        key = str(sticker_id or "").strip()
        if not key:
            raise ValueError("sticker_id required")
        current = self._items.get(key) or {
            "sticker_id": key,
            "tags": [],
            "persona_fit": True,
            "score_sum": 0,
            "score_count": 0,
            "send_count": 0,
            "updated_at": 0,
        }
        if tags is not None:
            current["tags"] = [str(tag).strip() for tag in tags if str(tag).strip()][:12]
        current["persona_fit"] = bool(persona_fit)
        current["updated_at"] = int(time.time())
        self._items[key] = _normalize_item(current)
        self.save()
        return dict(self._items[key])

    def pick_by_tag(self, tag: str) -> dict[str, Any] | None:
        needle = str(tag or "").strip().casefold()
        if not needle:
            return None
        candidates = [
            item
            for item in self._items.values()
            if item.get("persona_fit") and any(needle in str(t).casefold() for t in list(item.get("tags") or []))
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: (-int(item.get("send_count") or 0), str(item.get("sticker_id"))))
        # 偏向较少发送的条目，增加新鲜感
        candidates.sort(key=lambda item: (int(item.get("send_count") or 0), str(item.get("sticker_id"))))
        return dict(candidates[0])

    def record_feedback(self, sticker_id: str, *, score: int) -> dict[str, Any] | None:
        key = str(sticker_id or "").strip()
        item = self._items.get(key)
        if item is None:
            return None
        clamped = max(1, min(5, int(score)))
        item["score_sum"] = int(item.get("score_sum") or 0) + clamped
        item["score_count"] = int(item.get("score_count") or 0) + 1
        item["send_count"] = int(item.get("send_count") or 0) + 1
        count = max(1, int(item["score_count"]))
        avg = float(item["score_sum"]) / float(count)
        if count >= 3 and avg < 2.5:
            item["persona_fit"] = False
        item["updated_at"] = int(time.time())
        self._items[key] = _normalize_item(item)
        self.save()
        return dict(self._items[key])


def _normalize_item(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "sticker_id": str(raw.get("sticker_id") or "").strip(),
        "tags": [str(tag).strip() for tag in list(raw.get("tags") or []) if str(tag).strip()][:12],
        "persona_fit": bool(raw.get("persona_fit", True)),
        "score_sum": int(raw.get("score_sum") or 0),
        "score_count": int(raw.get("score_count") or 0),
        "send_count": int(raw.get("send_count") or 0),
        "updated_at": int(raw.get("updated_at") or 0),
    }


def upsert_sticker_candidate(
    store: StickerFitStore,
    *,
    sticker_id: str,
    tags: list[str] | None = None,
    persona_fit: bool = True,
) -> dict[str, Any]:
    return store.upsert(sticker_id=sticker_id, tags=tags, persona_fit=persona_fit)


def record_sticker_feedback(store: StickerFitStore, *, sticker_id: str, score: int) -> dict[str, Any] | None:
    return store.record_feedback(sticker_id, score=score)
