from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from pallas.core.foundation.paths import plugin_data_dir
from pallas.product.persona.catchphrase_extract import (
    clean_catchphrase_text,
    extract_catchphrase_candidates,
    is_catchphrase_habit,
)


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
    """写入一条已校验的短口癖；非整句接话应先经 extract。"""
    text = clean_catchphrase_text(saying)
    if int(bot_id) <= 0 or int(group_id) <= 0 or not is_catchphrase_habit(text):
        return None
    rows = _load()
    current = next((row for row in rows if row.bot_id == int(bot_id) and row.saying == text), None)
    if current is None:
        current = CatchphraseEntry(
            entry_id=f"catch-{uuid.uuid4().hex[:12]}",
            bot_id=int(bot_id),
            saying=text,
            occasion=clean_catchphrase_text(occasion)[:20],
            groups_seen=[int(group_id)],
        )
        rows.append(current)
    else:
        groups = sorted(set(current.groups_seen) | {int(group_id)})
        update: dict = {"support": current.support + 1, "groups_seen": groups, "updated_at": int(time.time())}
        if occasion and not current.occasion:
            update["occasion"] = clean_catchphrase_text(occasion)[:20]
        current = current.model_copy(update=update)
        rows[rows.index(next(row for row in rows if row.entry_id == current.entry_id))] = current
    _save(rows)
    return current


def propose_catchphrases_from_utterance(bot_id: int, group_id: int, text: str) -> list[CatchphraseEntry]:
    """从成功回复抽取短口癖并写入候选（规则路径）。"""
    out: list[CatchphraseEntry] = []
    for saying, occasion in extract_catchphrase_candidates(text):
        entry = propose_catchphrase_from_bot_success(bot_id, group_id, saying, occasion)
        if entry is not None:
            out.append(entry)
    return out


_LLM_MINE_AT: dict[tuple[int, int], int] = {}
_LLM_MINE_COOLDOWN_SEC = 600


def schedule_llm_catchphrase_mine(bot_id: int, group_id: int, text: str) -> None:
    """有事件循环时后台 LLM 补充抽取；按 bot+群冷却，失败静默。"""
    if int(bot_id) <= 0 or int(group_id) <= 0 or len(clean_catchphrase_text(text)) < 8:
        return
    key = (int(bot_id), int(group_id))
    now = int(time.time())
    last = _LLM_MINE_AT.get(key)
    if last is not None and now - last < _LLM_MINE_COOLDOWN_SEC:
        return
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _LLM_MINE_AT[key] = now
    loop.create_task(_llm_mine_catchphrases(int(bot_id), int(group_id), str(text)), name="catchphrase_llm_mine")


async def _llm_mine_catchphrases(bot_id: int, group_id: int, text: str) -> None:
    try:
        from pallas.product.persona.catchphrase_extract import extract_catchphrase_candidates_llm

        for saying, occasion in await extract_catchphrase_candidates_llm(text):
            propose_catchphrase_from_bot_success(bot_id, group_id, saying, occasion)
    except Exception:
        pass


def is_auto_promote_eligible(entry: CatchphraseEntry) -> bool:
    return (entry.support >= 3 and len(entry.groups_seen) >= 2) or entry.support >= 5


def promote_catchphrase(entry_id: str, *, force: bool = False) -> CatchphraseEntry | None:
    rows = _load()
    for index, row in enumerate(rows):
        if row.entry_id != entry_id:
            continue
        if not is_catchphrase_habit(row.saying):
            return None
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


def reject_weak_filler_catchphrases(bot_id: int | None = None) -> int:
    """把已入库的万能软答应口癖标为 rejected，切断正反馈。"""
    from pallas.product.persona.soft_agree_fillers import is_weak_catchphrase_saying

    rows = _load()
    changed = 0
    now = int(time.time())
    for index, row in enumerate(rows):
        if bot_id is not None and row.bot_id != int(bot_id):
            continue
        if row.status == "rejected":
            continue
        if not is_weak_catchphrase_saying(row.saying):
            continue
        rows[index] = row.model_copy(update={"status": "rejected", "updated_at": now})
        changed += 1
    if changed:
        _save(rows)
    return changed


def compile_catchphrase_prompt_lines(bot_id: int) -> list[str]:
    """口癖按场合软参考注入；勿写成每句必带的模板起手。"""
    lines: list[str] = []
    for row in list_catchphrases(bot_id, status="active"):
        if not is_catchphrase_habit(row.saying):
            continue
        occasion = clean_catchphrase_text(row.occasion) or "日常接话"
        lines.append(f"当「{occasion}」时，可以自然用「{row.saying}」来表达。")
    if not lines:
        return []
    return [
        "【表达习惯参考，请视情况自然使用；不要每句都带，禁止行行行/好好好/还行吧起手】",
        *lines,
    ]
