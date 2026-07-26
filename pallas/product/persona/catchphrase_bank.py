from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from pallas.core.foundation.paths import plugin_data_dir


class CatchphraseEntry(BaseModel):
    entry_id: str
    bot_id: int
    saying: str
    occasion: str = ""
    support: int = 1
    groups_seen: list[int] = Field(default_factory=list)
    status: Literal["candidate", "active", "rejected"] = "candidate"
    sources: list[str] = Field(default_factory=lambda: ["llm_success"])
    created_at: int = Field(default_factory=lambda: int(time.time()))
    updated_at: int = Field(default_factory=lambda: int(time.time()))


def _path() -> Path:
    root = (
        Path(os.environ["PALLAS_DATA_DIR"])
        if os.environ.get("PALLAS_DATA_DIR")
        else plugin_data_dir("pb_webui", create=True)
    )
    path = root / "expression_bank" / "catchphrases.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load() -> list[CatchphraseEntry]:
    if not _path().exists():
        return []
    rows = []
    for line in _path().read_text(encoding="utf-8").splitlines():
        try:
            rows.append(CatchphraseEntry.model_validate(json.loads(line)))
        except (TypeError, ValueError):
            pass
    return rows


def _save(rows: list[CatchphraseEntry]) -> None:
    _path().write_text(
        "".join(json.dumps(row.model_dump(mode="json"), ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )


def propose_catchphrase_from_bot_success(
    bot_id: int, group_id: int, saying: str, occasion: str = ""
) -> CatchphraseEntry | None:
    text = " ".join(str(saying or "").split())[:40]
    if int(bot_id) <= 0 or int(group_id) <= 0 or not text:
        return None
    rows = _load()
    current = next((row for row in rows if row.bot_id == int(bot_id) and row.saying == text), None)
    if current is None:
        current = CatchphraseEntry(
            entry_id=f"catch-{uuid.uuid4().hex[:12]}",
            bot_id=int(bot_id),
            saying=text,
            occasion=occasion,
            groups_seen=[int(group_id)],
        )
        rows.append(current)
    else:
        groups = sorted(set(current.groups_seen) | {int(group_id)})
        current = current.model_copy(
            update={"support": current.support + 1, "groups_seen": groups, "updated_at": int(time.time())}
        )
        rows[rows.index(next(row for row in rows if row.entry_id == current.entry_id))] = current
    _save(rows)
    return current


def is_auto_promote_eligible(entry: CatchphraseEntry) -> bool:
    return (entry.support >= 3 and len(entry.groups_seen) >= 2) or entry.support >= 5


def promote_catchphrase(entry_id: str, *, force: bool = False) -> CatchphraseEntry | None:
    rows = _load()
    for index, row in enumerate(rows):
        if row.entry_id != entry_id:
            continue
        if not force and not is_auto_promote_eligible(row):
            return None
        rows[index] = row.model_copy(update={"status": "active", "updated_at": int(time.time())})
        _save(rows)
        return rows[index]
    return None


def reject_catchphrase(entry_id: str) -> CatchphraseEntry | None:
    rows = _load()
    for index, row in enumerate(rows):
        if row.entry_id == entry_id:
            rows[index] = row.model_copy(update={"status": "rejected", "updated_at": int(time.time())})
            _save(rows)
            return rows[index]
    return None


def list_catchphrases(bot_id: int | None = None, *, status: str | None = None) -> list[CatchphraseEntry]:
    return [
        row
        for row in _load()
        if (bot_id is None or row.bot_id == int(bot_id)) and (status is None or row.status == status)
    ]


def compile_catchphrase_prompt_lines(bot_id: int) -> list[str]:
    return [f"可自然使用的口头禅：{row.saying}（{row.occasion}）" for row in list_catchphrases(bot_id, status="active")]
