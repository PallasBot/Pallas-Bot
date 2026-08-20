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

_ENTRY_ID_RE = re.compile(r"^catch-(\d+)-", re.ASCII)


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


def _base_dir() -> Path:
    root = (
        Path(os.environ["PALLAS_DATA_DIR"])
        if os.environ.get("PALLAS_DATA_DIR")
        else plugin_data_dir("pb_webui", create=True)
    )
    path = root / "expression_bank" / "catchphrase_bank"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pending_dir() -> Path:
    path = _base_dir() / "pending"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _merged_dir() -> Path:
    path = _base_dir() / "merged"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _shard_path(bot_id: int, *, pending: bool) -> Path:
    shard_dir = _pending_dir() if pending else _merged_dir()
    return shard_dir / f"{int(bot_id)}.jsonl"


def _bot_id_from_entry_id(entry_id: str) -> int:
    match = _ENTRY_ID_RE.match(str(entry_id or ""))
    return int(match.group(1)) if match else 0


def _iter_rows(path):
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            yield CatchphraseEntry.model_validate(json.loads(line))
        except (TypeError, ValueError):
            pass


def _fold(merged: list[CatchphraseEntry], pending: list[CatchphraseEntry]) -> list[CatchphraseEntry]:
    index = {row.entry_id: row for row in merged}
    for delta in pending:
        current = index.get(delta.entry_id)
        if current is None:
            index[delta.entry_id] = delta
            continue
        groups = sorted(set(current.groups_seen + delta.groups_seen))
        feedback = {key: dict(value) for key, value in current.scene_feedback.items()}
        new_outcomes = [o for o in delta.applied_outcome_ids if o not in current.applied_outcome_ids]
        if new_outcomes:
            for scene, stats in delta.scene_feedback.items():
                merged_stats = feedback.setdefault(scene, {"uses": 0, "score": 0})
                merged_stats["uses"] = int(merged_stats.get("uses", 0)) + int(stats.get("uses", 0))
                merged_stats["score"] = int(merged_stats.get("score", 0)) + int(stats.get("score", 0))
        status = current.status if current.status == "rejected" else delta.status
        current = current.model_copy(
            update={
                "support": current.support + max(0, delta.support),
                "groups_seen": groups,
                "status": status,
                "updated_at": max(current.updated_at, delta.updated_at),
                "scene_feedback": feedback,
                "applied_outcome_ids": list({*current.applied_outcome_ids, *delta.applied_outcome_ids}),
            }
        )
        index[delta.entry_id] = current
    return list(index.values())


def _load(bot_id: int) -> list[CatchphraseEntry]:
    merged = list(_iter_rows(_shard_path(bot_id, pending=False)))
    pending = list(_iter_rows(_shard_path(bot_id, pending=True)))
    return _fold(merged, pending)


def _save(bot_id: int, rows: list[CatchphraseEntry]) -> None:
    body = "".join(json.dumps(row.model_dump(mode="json"), ensure_ascii=False) + "\n" for row in rows)
    _shard_path(bot_id, pending=False).write_text(body, encoding="utf-8")


def _append(bot_id: int, entries: list[CatchphraseEntry]) -> None:
    from pallas.core.foundation.fs_lock import interprocess_file_lock

    if not entries:
        return
    path = _shard_path(bot_id, pending=True)
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        body = "".join(json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n" for item in entries)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(body)


def _canonical_catchphrase_entry_id(row: CatchphraseEntry) -> str:
    prefix = f"catch-{int(row.bot_id)}-"
    if row.entry_id.startswith(prefix):
        return row.entry_id
    tail = str(re.sub(r"^catch-", "", row.entry_id or "")).strip()
    return f"{prefix}{tail or uuid.uuid4().hex[:12]}"


def migrate_legacy_catchphrases() -> bool:
    legacy = _path()
    if not legacy.exists():
        return False
    by_bot: dict[int, list[CatchphraseEntry]] = {}
    for row in _iter_rows(legacy):
        by_bot.setdefault(int(row.bot_id), []).append(row)
    for bid, rows in sorted(by_bot.items()):
        rows = [row.model_copy(update={"entry_id": _canonical_catchphrase_entry_id(row)}) for row in rows]
        _save(bid, rows)
    legacy.replace(legacy.with_suffix(".jsonl.migrated.bak"))
    return True


def merge_catchphrase_bot(bot_id: int) -> None:
    from pallas.core.foundation.fs_lock import interprocess_file_lock

    path = _shard_path(bot_id, pending=True)
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        pending = list(_iter_rows(path))
        if not pending:
            return
        merged = _fold(list(_iter_rows(_shard_path(bot_id, pending=False))), pending)
        _save(bot_id, merged)
        path.unlink(missing_ok=True)


def merge_all_catchphrase_pending(limit: int = 256) -> int:
    merged_count = 0
    for path in sorted(_pending_dir().glob("*.jsonl")):
        if merged_count >= max(0, int(limit)):
            break
        try:
            bid = int(path.stem)
        except ValueError:
            continue
        merge_catchphrase_bot(bid)
        merged_count += 1
    return merged_count


def propose_catchphrase_from_bot_success(
    bot_id: int, group_id: int, saying: str, occasion: str = ""
) -> CatchphraseEntry | None:
    """Append an O(1) delta for a valid short catchphrase; returns the folded entry."""
    text = clean_catchphrase_text(saying)
    if int(bot_id) <= 0 or int(group_id) <= 0 or not is_catchphrase_habit(text):
        return None
    bid = int(bot_id)
    existing_id: str | None = None
    from pallas.core.foundation.fs_lock import interprocess_file_lock

    path = _shard_path(bid, pending=True)
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        for row in _load(bid):
            if row.bot_id == bid and row.saying == text:
                existing_id = row.entry_id
                break
        if existing_id is None:
            delta = CatchphraseEntry(
                entry_id=f"catch-{bid}-{uuid.uuid4().hex[:12]}",
                bot_id=bid,
                saying=text,
                occasion=normalize_occasion_tag(clean_catchphrase_text(occasion))[:20],
                groups_seen=[int(group_id)],
            )
            _append_lines_locked(path, [delta])
        else:
            folded = next((row for row in _load(bid) if row.entry_id == existing_id), None)
            if folded is None:
                return None
            support = int(folded.support) + 1
            groups = sorted(set(folded.groups_seen) | {int(group_id)})
            update: dict = {
                "support": support,
                "groups_seen": groups,
                "updated_at": int(time.time()),
            }
            occasion_norm = normalize_occasion_tag(clean_catchphrase_text(occasion))[:20]
            if occasion_norm and not folded.occasion:
                update["occasion"] = occasion_norm
            delta = folded.model_copy(update=update)
            _append_lines_locked(path, [delta])
        folded = _fold(list(_iter_rows(_shard_path(bid, pending=False))), [delta])
        return folded[0] if folded else delta


def _append_lines_locked(path: Path, entries: list[CatchphraseEntry]) -> None:
    body = "".join(json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n" for item in entries)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(body)


def propose_catchphrases_from_utterance(bot_id: int, group_id: int, text: str) -> list[CatchphraseEntry]:
    out: list[CatchphraseEntry] = []
    for saying, occasion in extract_catchphrase_candidates(text):
        entry = propose_catchphrase_from_bot_success(bot_id, group_id, saying, occasion)
        if entry is not None:
            out.append(entry)
    return out


_LLM_MINE_AT: dict[tuple[int, int], int] = {}
_LLM_MINE_COOLDOWN_SEC = 600


def schedule_llm_catchphrase_mine(bot_id: int, group_id: int, text: str) -> None:
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


def _find_entry_any_shard(entry_id: str) -> CatchphraseEntry | None:
    bid = _bot_id_from_entry_id(entry_id)
    if bid > 0:
        for row in _load(bid):
            if row.entry_id == entry_id:
                return row
        return None
    for path in sorted(_merged_dir().glob("*.jsonl")):
        for row in _iter_rows(path):
            if row.entry_id == entry_id:
                return row
        for row in _iter_rows(_shard_path(int(path.stem), pending=True)):
            if row.entry_id == entry_id:
                return row
    return None


def promote_catchphrase(entry_id: str, *, force: bool = False) -> CatchphraseEntry | None:
    from pallas.core.foundation.fs_lock import interprocess_file_lock

    target_id = str(entry_id or "").strip()
    if not target_id:
        return None
    bid = _bot_id_from_entry_id(target_id)
    if bid <= 0:
        return None
    path = _shard_path(bid, pending=True)
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        current = next((row for row in _load(bid) if row.entry_id == target_id), None)
        if current is None:
            return None
        if not is_catchphrase_habit(current.saying) or (not force and not is_auto_promote_eligible(current)):
            return None
        delta = current.model_copy(update={"status": "active", "updated_at": int(time.time())})
        _append_lines_locked(path, [delta])
        return delta


def reject_catchphrase(entry_id: str) -> CatchphraseEntry | None:
    from pallas.core.foundation.fs_lock import interprocess_file_lock

    target_id = str(entry_id or "").strip()
    if not target_id:
        return None
    bid = _bot_id_from_entry_id(target_id)
    if bid <= 0:
        return None
    path = _shard_path(bid, pending=True)
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        current = next((row for row in _load(bid) if row.entry_id == target_id), None)
        if current is None:
            return None
        delta = current.model_copy(update={"status": "rejected", "updated_at": int(time.time())})
        _append_lines_locked(path, [delta])
        return delta


def list_catchphrases(bot_id: int | None = None, *, status: str | None = None) -> list[CatchphraseEntry]:
    if bot_id is None:
        rows: list[CatchphraseEntry] = []
        for path in sorted(_merged_dir().glob("*.jsonl")):
            rows.extend(_load(int(path.stem)))
        return [row for row in rows if status is None or row.status == status]
    return [row for row in _load(int(bot_id)) if status is None or row.status == status]


def record_catchphrase_outcome(entry_ids: list[str], *, scene: str, score_delta: int, outcome_id: str) -> None:
    targets = {str(item).strip() for item in entry_ids if str(item).strip()}
    if not targets:
        return
    scene_key = normalize_occasion_tag(str(scene or ""))
    now = int(time.time())
    by_bot: dict[int, list[CatchphraseEntry]] = {}
    for target in targets:
        bid = _bot_id_from_entry_id(target)
        if bid <= 0:
            continue
        by_bot.setdefault(bid, []).append(
            CatchphraseEntry(
                entry_id=target,
                bot_id=bid,
                saying="",
                support=0,
                groups_seen=[],
                status="candidate",
                sources=["llm_success"],
                created_at=now,
                updated_at=now,
                scene_feedback={scene_key: {"uses": 1, "score": int(score_delta)}} if scene_key else {},
                applied_outcome_ids=[outcome_id],
            )
        )
    for bid, deltas in sorted(by_bot.items()):
        _append(bid, deltas)


def reject_weak_filler_catchphrases(bot_id: int | None = None) -> int:
    """Mark boring soft-reply catchphrases as rejected, cutting positive feedback."""
    from pallas.core.foundation.fs_lock import interprocess_file_lock
    from pallas.product.persona.soft_agree_fillers import is_weak_catchphrase_saying

    targets: list[int]
    if bot_id is not None:
        targets = [int(bot_id)]
    else:
        targets = [int(path.stem) for path in sorted(_merged_dir().glob("*.jsonl"))]
    changed = 0
    now = int(time.time())
    for bid in targets:
        path = _shard_path(bid, pending=True)
        with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
            rows = _load(bid)
            rejected_deltas: list[CatchphraseEntry] = []
            for row in rows:
                if row.status == "rejected" or not is_weak_catchphrase_saying(row.saying):
                    continue
                rejected_deltas.append(row.model_copy(update={"status": "rejected", "updated_at": now}))
                changed += 1
            if rejected_deltas:
                _append_lines_locked(path, rejected_deltas)
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
