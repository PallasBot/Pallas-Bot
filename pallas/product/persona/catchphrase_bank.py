from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from pallas.core.foundation.paths import plugin_data_dir
from pallas.product.persona.catchphrase_extract import (
    clean_catchphrase_text,
    extract_catchphrase_candidates,
    is_catchphrase_habit,
)
from pallas.product.persona.occasion import OccasionTag, normalize_occasion_tag


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
    scene_feedback: dict[str, dict[str, int]] = Field(default_factory=dict)
    applied_outcome_ids: list[str] = Field(default_factory=list)

    @field_validator("occasion", mode="before")
    @classmethod
    def normalize_occasion(cls, value: object) -> str:
        return normalize_occasion_tag(clean_catchphrase_text(str(value or "")))


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
    from pallas.core.foundation.fs_lock import interprocess_file_lock

    path = _path()
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        rows = _load()
        current = next((row for row in rows if row.bot_id == int(bot_id) and row.saying == text), None)
        if current is None:
            current = CatchphraseEntry(
                entry_id=f"catch-{uuid.uuid4().hex[:12]}",
                bot_id=int(bot_id),
                saying=text,
                occasion=normalize_occasion_tag(clean_catchphrase_text(occasion))[:20],
                groups_seen=[int(group_id)],
            )
            rows.append(current)
        else:
            groups = sorted(set(current.groups_seen) | {int(group_id)})
            update: dict = {"support": current.support + 1, "groups_seen": groups, "updated_at": int(time.time())}
            if occasion and not current.occasion:
                update["occasion"] = normalize_occasion_tag(clean_catchphrase_text(occasion))[:20]
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
    from pallas.core.foundation.fs_lock import interprocess_file_lock

    path = _path()
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        rows = _load()
        for index, row in enumerate(rows):
            if row.entry_id != entry_id:
                continue
            if not is_catchphrase_habit(row.saying) or (not force and not is_auto_promote_eligible(row)):
                return None
            rows[index] = row.model_copy(update={"status": "active", "updated_at": int(time.time())})
            _save(rows)
            return rows[index]
    return None


def reject_catchphrase(entry_id: str) -> CatchphraseEntry | None:
    from pallas.core.foundation.fs_lock import interprocess_file_lock

    path = _path()
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
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


def record_catchphrase_outcome(entry_ids: list[str], *, scene: str, score_delta: int, outcome_id: str) -> None:
    targets = {str(item).strip() for item in entry_ids if str(item).strip()}
    if not targets:
        return
    from pallas.core.foundation.fs_lock import atomic_write_text, interprocess_file_lock

    path = _path()
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        rows = _load()
        changed = False
        for index, row in enumerate(rows):
            if row.entry_id not in targets or outcome_id in row.applied_outcome_ids:
                continue
            feedback = {key: dict(value) for key, value in row.scene_feedback.items()}
            stat = feedback.setdefault(normalize_occasion_tag(scene), {"uses": 0, "score": 0})
            stat["uses"] = int(stat.get("uses", 0)) + 1
            stat["score"] = int(stat.get("score", 0)) + int(score_delta)
            rows[index] = row.model_copy(
                update={"scene_feedback": feedback, "applied_outcome_ids": [*row.applied_outcome_ids, outcome_id]}
            )
            changed = True
        if changed:
            body = "".join(json.dumps(row.model_dump(mode="json"), ensure_ascii=False) + "\n" for row in rows)
            atomic_write_text(path, body)


def reject_weak_filler_catchphrases(bot_id: int | None = None) -> int:
    """把已入库的万能软答应口癖标为 rejected，切断正反馈。"""
    from pallas.core.foundation.fs_lock import interprocess_file_lock
    from pallas.product.persona.soft_agree_fillers import is_weak_catchphrase_saying

    path = _path()
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        rows = _load()
        changed = 0
        now = int(time.time())
        for index, row in enumerate(rows):
            if bot_id is not None and row.bot_id != int(bot_id):
                continue
            if row.status == "rejected" or not is_weak_catchphrase_saying(row.saying):
                continue
            rows[index] = row.model_copy(update={"status": "rejected", "updated_at": now})
            changed += 1
        if changed:
            _save(rows)
        return changed


_SCENE_OCCASION_TOKENS: dict[str, tuple[str, ...]] = {
    "banter": ("玩笑", "接梗", "吐槽", "乐", "梗", "调侃"),
    "venting": ("安抚", "情绪", "吐槽", "安慰"),
    "provocation": ("顶嘴", "吐槽", "挑衅", "怼"),
    "light_help": ("帮助", "说明", "回答", "解释"),
    "smalltalk": ("日常", "闲聊", "口头禅", "语气", "接话"),
    "group_threading": ("多人", "接话", "日常", "插话"),
}


def _query_keywords(text: str) -> set[str]:
    plain = clean_catchphrase_text(text).lower()
    keywords: set[str] = set()
    cjk = "".join(char for char in plain if "\u4e00" <= char <= "\u9fff")
    keywords.update(cjk[index : index + 2] for index in range(max(0, len(cjk) - 1)))
    keywords.update(token.lower() for token in re.findall(r"[a-z0-9_]{2,}", plain, flags=re.IGNORECASE))
    return keywords


def score_catchphrase_for_turn(
    entry: CatchphraseEntry,
    *,
    user_text: str = "",
    scene: str = "",
) -> int | None:
    """按用户句与场景给口癖打分；无关则 None。"""
    if entry.status == "rejected" or not is_catchphrase_habit(entry.saying):
        return None
    occasion = clean_catchphrase_text(entry.occasion) or "日常接话"
    candidate = f"{occasion} {entry.saying}".lower()
    score = 40 + min(max(1, int(entry.support)), 10)
    kw_hits = sum(keyword in candidate for keyword in _query_keywords(user_text))
    score += min(30, 8 * kw_hits)
    scene_key = normalize_occasion_tag(str(scene or "").strip())
    scene_tokens = _SCENE_OCCASION_TOKENS.get(scene_key, ())
    scene_tags = {
        OccasionTag.PROVOCATION,
        OccasionTag.BANTER,
        OccasionTag.SMALLTALK,
        OccasionTag.VENTING,
        OccasionTag.GROUP_THREADING,
        OccasionTag.LIGHT_HELP,
    }
    if occasion in scene_tags and scene_key and occasion != scene_key:
        return None
    scene_matches = occasion == scene_key or bool(scene_tokens and any(token in candidate for token in scene_tokens))
    if scene_matches:
        score += 24
    elif scene_key in {"banter", "venting", "provocation", "light_help"} and occasion in {
        "口头禅",
        "日常接话",
        "语气尾巴",
    }:
        score -= 10
    if kw_hits == 0 and scene_key and not scene_matches:
        # 无关键词且场合不对：仅保留高支持自称梗作弱候选
        if entry.occasion == "自称梗" and entry.support >= 3:
            score -= 15
        else:
            return None
    feedback = entry.scene_feedback.get(scene_key, {}) if scene_key else {}
    if feedback.get("uses"):
        score += max(-6, min(6, int(feedback.get("score", 0))))
    return score


def select_catchphrases_for_turn(
    bot_id: int,
    *,
    user_text: str = "",
    scene: str = "",
    limit: int = 2,
) -> list[CatchphraseEntry]:
    scored: list[tuple[int, CatchphraseEntry]] = []
    for row in list_catchphrases(int(bot_id), status="active"):
        score = score_catchphrase_for_turn(row, user_text=user_text, scene=scene)
        if score is None:
            continue
        scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], -item[1].updated_at, item[1].entry_id))
    return [row for _, row in scored[: max(0, int(limit))]]


def compile_catchphrase_prompt_lines(
    bot_id: int,
    *,
    user_text: str = "",
    scene: str = "",
    limit: int = 2,
) -> list[str]:
    lines, _rows = compile_catchphrase_prompt_with_entries(bot_id, user_text=user_text, scene=scene, limit=limit)
    return lines


def compile_catchphrase_prompt_with_entries(
    bot_id: int,
    *,
    user_text: str = "",
    scene: str = "",
    limit: int = 2,
) -> tuple[list[str], list[CatchphraseEntry]]:
    """按本轮场合选入口癖；无线索时不强行塞入多条。"""
    if int(limit) <= 0:
        return [], []
    if str(user_text or "").strip() or str(scene or "").strip():
        rows = select_catchphrases_for_turn(
            int(bot_id),
            user_text=user_text,
            scene=scene,
            limit=limit,
        )
    else:
        # 无线索时最多保留 1 条高支持口癖
        rows = [row for row in list_catchphrases(int(bot_id), status="active") if is_catchphrase_habit(row.saying)]
        rows.sort(key=lambda row: (-int(row.support), -int(row.updated_at)))
        rows = rows[: min(1, int(limit))]
    lines: list[str] = []
    for row in rows:
        occasion = clean_catchphrase_text(row.occasion) or "日常接话"
        lines.append(f"当「{occasion}」时，可以自然用「{row.saying}」来表达。")
    if not lines:
        return [], []
    return [
        "【表达习惯参考，请视情况自然使用；不要每句都带，禁止行行行/好好好/还行吧起手】",
        *lines,
    ], rows
