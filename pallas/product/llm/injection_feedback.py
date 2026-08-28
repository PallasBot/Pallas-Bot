"""群级 LLM 负反馈治理账本：幂等 outcome、30 天半衰评分与 ambient 禁用短语过滤。"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import TYPE_CHECKING, Any, Literal

from nonebot import logger
from pydantic import BaseModel, ConfigDict, Field

from pallas.core.foundation.fs_lock import atomic_write_text, interprocess_file_lock
from pallas.core.foundation.logging import log_rate_limited

if TYPE_CHECKING:
    from pathlib import Path

_HALF_LIFE_SEC = 30 * 86400
_EFFECT_LEASE_SEC = 300
_MAX_PREVIEW_LEN = 120
_MIN_PHRASE_LEN = 2
_MAX_SNAPSHOT_ENTRIES_PER_TYPE = 64
_MAX_BLACKLIST_PHRASES_PER_OUTCOME = 32

_SOURCE_SCORES = {
    "ambient": -1.0,
    "semantic": -2.0,
    "memory": -1.0,
    "knowledge": 0.0,
    "style_profile": 0.0,
}

_EXPLICIT_RISK_WORDS = frozenset({
    "鸡巴",
    "傻逼",
    "妈逼",
    "尼玛",
    "贱人",
    "婊子",
    "畜生",
    "脑残",
    "白痴",
    "废物",
    "去死",
    "滚蛋",
    "草泥马",
    "操你妈",
})

_FUNCTION_WORDS = frozenset({
    "的",
    "了",
    "吗",
    "呢",
    "啊",
    "吧",
    "嘛",
    "哦",
    "嗯",
    "呀",
    "么",
    "是",
    "在",
    "有",
    "没",
    "不",
    "都",
    "就",
    "也",
    "很",
    "好",
    "这",
    "那",
    "你",
    "我",
    "他",
    "她",
    "们",
    "什么",
    "怎么",
    "这样",
    "那样",
    "这个",
    "那个",
    "这样的",
    "那样的",
    "可以",
    "可以的",
    "不要",
    "不会",
    "没有",
    "不是",
    "是的",
    "好的",
    "好吧",
    "对吧",
    "你们",
    "我们",
    "他们",
    "她们",
    "大家",
    "一个",
    "一下",
    "然后",
    "所以",
    "但是",
    "就是",
    "还是",
    "真的",
    "其实",
    "嗯嗯",
    "哈哈",
    "嘿嘿",
    "对对",
})


class InjectionSnapshot(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    ambient_turns: list[dict[str, Any]] = Field(default_factory=list)
    semantic_examples: list[dict[str, Any]] = Field(default_factory=list)
    memory_entries: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_chunks: list[dict[str, Any]] = Field(default_factory=list)
    self_aliases: list[dict[str, Any]] = Field(default_factory=list)
    style_profile: dict[str, Any] = Field(default_factory=dict)


class SourceDecision(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    kind: str
    source_id: str = ""
    score: float = 0.0
    confidence: str = "low"
    matched_phrase: str = ""
    blacklist_phrases: list[str] = Field(default_factory=list)
    audit_only: bool = False
    remove_alias: bool = False
    text_preview: str = ""


class NegativeOutcomeApplyResult(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    applied: bool = False
    outcome_id: str = ""
    bot_id: int = 0
    group_id: int = 0
    created_at: int = 0
    decisions: list[SourceDecision] = Field(default_factory=list)
    blacklist_phrases: list[str] = Field(default_factory=list)


def injection_governance_dir(*, create: bool = True) -> Path:
    from pallas.product.llm.repeater_feedback import feedback_base_dir

    return feedback_base_dir(create=create) / "injection_governance"


def outcomes_path(*, create: bool = True) -> Path:
    return injection_governance_dir(create=create) / "outcomes.jsonl"


def _preview(text: str) -> str:
    plain = str(text or "").strip()
    if len(plain) <= _MAX_PREVIEW_LEN:
        return plain
    return plain[:_MAX_PREVIEW_LEN]


def _iter_outcomes(path: Path):
    if not path.exists():
        return
    with path.open(encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(row, dict):
                yield row


def _load_outcomes() -> list[dict[str, Any]]:
    path = outcomes_path(create=False)
    try:
        return list(_iter_outcomes(path))
    except OSError:
        log_rate_limited(
            logger,
            "warning",
            "llm.injection_governance.read_failed",
            "injection governance ledger read failed: [{}]",
            path,
        )
        return []


def _strip_function_words(text: str) -> str:
    result: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        longest = ""
        for word in _FUNCTION_WORDS:
            if len(word) > len(longest) and text.startswith(word, i):
                longest = word
        if longest:
            i += len(longest)
            continue
        result.append(text[i])
        i += 1
    return "".join(result)


def _meaningful_phrases(reply_text: str, source_text: str) -> list[str]:
    phrases: list[str] = []
    for word in _EXPLICIT_RISK_WORDS:
        if word in reply_text and word in source_text and word not in phrases:
            phrases.append(word)
    best_core = ""
    best_len = 0
    source_len = len(source_text)
    for start in range(source_len):
        for end in range(start + _MIN_PHRASE_LEN, source_len + 1):
            sub_len = end - start
            if sub_len <= best_len:
                continue
            sub = source_text[start:end]
            if sub not in reply_text:
                continue
            core = _strip_function_words(sub)
            if len(core) < _MIN_PHRASE_LEN:
                continue
            best_len = sub_len
            best_core = core
    if best_core and best_core not in phrases:
        phrases.append(best_core)
    return phrases


def _snapshot_candidates(snapshot: InjectionSnapshot) -> list[tuple[str, str, str, list[str]]]:
    candidates: list[tuple[str, str, str, list[str]]] = []
    for turn in snapshot.ambient_turns[:_MAX_SNAPSHOT_ENTRIES_PER_TYPE]:
        source_id = str(turn.get("turn_id") or "")
        text = _preview(str(turn.get("text_preview") or ""))
        if source_id and text:
            candidates.append(("ambient", source_id, text, [text]))
    for example in snapshot.semantic_examples[:_MAX_SNAPSHOT_ENTRIES_PER_TYPE]:
        source_id = str(example.get("example_id") or "")
        trigger = _preview(str(example.get("trigger") or ""))
        reply = _preview(str(example.get("reply") or ""))
        if source_id:
            candidates.append(("semantic", source_id, reply, [reply, trigger]))
    for entry in snapshot.memory_entries[:_MAX_SNAPSHOT_ENTRIES_PER_TYPE]:
        source_id = str(entry.get("entry_id") or "")
        text = _preview(str(entry.get("text_preview") or ""))
        if source_id and text:
            candidates.append(("memory", source_id, text, [text]))
    return candidates


def _build_source_decisions(reply_text: str, snapshot: InjectionSnapshot) -> list[SourceDecision]:
    decisions: list[SourceDecision] = []
    for kind, source_id, preview, texts in _snapshot_candidates(snapshot):
        matched_phrases: list[str] = []
        for text in texts:
            if not text:
                continue
            for phrase in _meaningful_phrases(reply_text, text):
                if len(matched_phrases) >= _MAX_BLACKLIST_PHRASES_PER_OUTCOME:
                    break
                if phrase not in matched_phrases:
                    matched_phrases.append(_preview(phrase))
        decisions.append(
            SourceDecision(
                kind=kind,
                source_id=source_id,
                score=_SOURCE_SCORES.get(kind, 0.0),
                confidence="high" if matched_phrases else "low",
                matched_phrase=matched_phrases[0] if matched_phrases else "",
                blacklist_phrases=matched_phrases if kind == "ambient" else [],
                text_preview=_preview(preview),
            )
        )
    decisions.extend(
        SourceDecision(
            kind="knowledge",
            source_id=str(chunk.get("chunk_id") or chunk.get("source_id") or ""),
            score=0.0,
            audit_only=True,
        )
        for chunk in snapshot.knowledge_chunks[:_MAX_SNAPSHOT_ENTRIES_PER_TYPE]
    )
    if snapshot.style_profile:
        decisions.append(SourceDecision(kind="style_profile", source_id="", score=0.0, audit_only=True))
    for alias_entry in snapshot.self_aliases[:_MAX_SNAPSHOT_ENTRIES_PER_TYPE]:
        alias = _preview(str(alias_entry.get("alias") or ""))
        if not alias:
            continue
        phrases = _meaningful_phrases(reply_text, alias)
        if phrases:
            decisions.append(
                SourceDecision(
                    kind="self_alias",
                    source_id=alias,
                    score=0.0,
                    confidence="high",
                    matched_phrase=phrases[0],
                    remove_alias=True,
                    text_preview=_preview(alias),
                )
            )
    return decisions


def _scope_match(row: dict[str, Any], bot_id: int, group_id: int) -> bool:
    try:
        return int(row.get("bot_id") or 0) == int(bot_id) and int(row.get("group_id") or 0) == int(group_id)
    except (TypeError, ValueError):
        return False


def _outcome_has_effect(row: dict[str, Any], kind: str) -> bool:
    target_kind = str(kind or "").strip()
    for item in row.get("decisions") or []:
        if not isinstance(item, dict) or str(item.get("kind") or "").strip() != target_kind:
            continue
        if target_kind == "self_alias" and bool(item.get("remove_alias")) and item.get("source_id"):
            return True
    return False


def _effect_state(effects: Any, kind: str) -> str:
    effect = effects.get(kind) if isinstance(effects, dict) else None
    if not isinstance(effect, dict):
        return "pending"
    if bool(effect.get("completed")) or effect.get("state") == "completed":
        return "completed"
    if effect.get("state") == "cancelled":
        return "cancelled"
    if effect.get("state") == "applying":
        return "applying"
    if effect.get("state") == "claimed":
        return "claimed"
    return "pending"


def _effect_claim_expired(effect: Any, *, now: int) -> bool:
    if not isinstance(effect, dict):
        return False
    claimed_at = effect.get("claimed_at")
    lease_id = str(effect.get("lease_id") or "").strip()
    try:
        return not lease_id or int(claimed_at) + _EFFECT_LEASE_SEC <= now
    except (TypeError, ValueError):
        return True


def claim_negative_outcome_effect(
    *,
    outcome_id: str,
    bot_id: int,
    group_id: int,
    kind: str,
    now: int | None = None,
) -> str | None:
    path = outcomes_path(create=False)
    claimed_at = int(now) if now is not None else int(time.time())
    try:
        with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
            rows = list(_iter_outcomes(path))
            for row in rows:
                if not _scope_match(row, bot_id, group_id) or str(row.get("outcome_id") or "") != outcome_id:
                    continue
                if row.get("undo"):
                    return None
                if not _outcome_has_effect(row, kind):
                    return None
                effects = row.setdefault("effects", {})
                if not isinstance(effects, dict):
                    effects = {}
                    row["effects"] = effects
                effect = effects.get(kind)
                state = _effect_state(effects, kind)
                if state not in {"pending", "claimed"} or (
                    state == "claimed" and not _effect_claim_expired(effect, now=claimed_at)
                ):
                    return None
                lease_id = uuid.uuid4().hex
                effects[kind] = {"state": "claimed", "claimed_at": claimed_at, "lease_id": lease_id}
                atomic_write_text(path, "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in rows))
                return lease_id
    except OSError:
        log_rate_limited(
            logger,
            "warning",
            "llm.injection_governance.effect_claim_failed",
            "injection governance effect claim update failed",
        )
    return None


def begin_negative_outcome_effect(*, outcome_id: str, bot_id: int, group_id: int, kind: str, lease_id: str) -> bool:
    path = outcomes_path(create=False)
    try:
        with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
            rows = list(_iter_outcomes(path))
            for row in rows:
                if not _scope_match(row, bot_id, group_id) or str(row.get("outcome_id") or "") != outcome_id:
                    continue
                if row.get("undo") or not _outcome_has_effect(row, kind):
                    return False
                effects = row.setdefault("effects", {})
                if not isinstance(effects, dict):
                    return False
                effect = effects.get(kind)
                if (
                    _effect_state(effects, kind) != "claimed"
                    or not isinstance(effect, dict)
                    or str(effect.get("lease_id") or "") != str(lease_id or "")
                ):
                    return False
                effects[kind] = {"state": "applying", "lease_id": lease_id}
                atomic_write_text(path, "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in rows))
                return True
    except OSError:
        log_rate_limited(
            logger,
            "warning",
            "llm.injection_governance.effect_begin_failed",
            "injection governance effect begin update failed",
        )
    return False


def release_negative_outcome_effect_claim(
    *, outcome_id: str, bot_id: int, group_id: int, kind: str, lease_id: str
) -> bool:
    path = outcomes_path(create=False)
    try:
        with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
            rows = list(_iter_outcomes(path))
            for row in rows:
                if not _scope_match(row, bot_id, group_id) or str(row.get("outcome_id") or "") != outcome_id:
                    continue
                if row.get("undo"):
                    return False
                if not _outcome_has_effect(row, kind) or _effect_state(row.get("effects"), kind) not in {
                    "claimed",
                    "applying",
                }:
                    return False
                effects = row.setdefault("effects", {})
                if not isinstance(effects, dict):
                    effects = {}
                    row["effects"] = effects
                effect = effects.get(kind)
                if not isinstance(effect, dict) or str(effect.get("lease_id") or "") != str(lease_id or ""):
                    return False
                effects[kind] = {"state": "pending"}
                atomic_write_text(path, "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in rows))
                return True
    except OSError:
        log_rate_limited(
            logger,
            "warning",
            "llm.injection_governance.effect_release_failed",
            "injection governance effect claim release failed",
        )
    return False


def mark_negative_outcome_effect_completed(
    *, outcome_id: str, bot_id: int, group_id: int, kind: str, lease_id: str
) -> bool:
    path = outcomes_path(create=False)
    try:
        with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
            rows = list(_iter_outcomes(path))
            for row in rows:
                if not _scope_match(row, bot_id, group_id) or str(row.get("outcome_id") or "") != outcome_id:
                    continue
                if row.get("undo"):
                    return False
                if not _outcome_has_effect(row, kind) or _effect_state(row.get("effects"), kind) != "applying":
                    return False
                effects = row.setdefault("effects", {})
                if not isinstance(effects, dict):
                    effects = {}
                    row["effects"] = effects
                effect = effects.get(kind)
                if not isinstance(effect, dict) or str(effect.get("lease_id") or "") != str(lease_id or ""):
                    return False
                effects[kind] = {"state": "completed", "completed": True}
                atomic_write_text(path, "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in rows))
                return True
    except OSError:
        log_rate_limited(
            logger,
            "warning",
            "llm.injection_governance.effect_mark_failed",
            "injection governance effect completion update failed",
        )
    return False


def apply_negative_outcome(
    *,
    outcome_id: str,
    bot_id: int,
    group_id: int,
    reply_text: str,
    injection_snapshot: dict[str, Any] | InjectionSnapshot,
    actor_id: str = "",
    reason: str = "",
    now: int | None = None,
) -> NegativeOutcomeApplyResult:
    """Append one idempotent group-scoped outcome and return its source decisions."""
    target_outcome_id = str(outcome_id or "").strip()
    target_bot_id = int(bot_id)
    target_group_id = int(group_id)
    created_at = int(now) if now is not None else int(time.time())
    if not target_outcome_id:
        return NegativeOutcomeApplyResult(applied=False)

    if isinstance(injection_snapshot, InjectionSnapshot):
        snapshot = injection_snapshot
    else:
        try:
            snapshot = InjectionSnapshot.model_validate(injection_snapshot or {})
        except (TypeError, ValueError):
            snapshot = InjectionSnapshot()

    plain_reply = str(reply_text or "").strip()
    decisions = _build_source_decisions(_preview(plain_reply), snapshot)
    blacklist_phrases: list[str] = []
    for decision in decisions:
        for phrase in decision.blacklist_phrases:
            if len(blacklist_phrases) >= _MAX_BLACKLIST_PHRASES_PER_OUTCOME:
                break
            phrase = _preview(phrase)
            if phrase not in blacklist_phrases:
                blacklist_phrases.append(phrase)

    outcome = {
        "outcome_id": target_outcome_id,
        "bot_id": target_bot_id,
        "group_id": target_group_id,
        "created_at": created_at,
        "reply_text": _preview(plain_reply),
        "actor_id": _preview(str(actor_id or "")),
        "reason": _preview(str(reason or "")),
        "decisions": [decision.model_dump(mode="json") for decision in decisions],
        "blacklist_phrases": blacklist_phrases,
        "effects": {},
        "undo": False,
        "undone_at": 0,
    }
    path = outcomes_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(outcome, ensure_ascii=False) + "\n"
        with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
            for row in list(_iter_outcomes(path)):
                if (
                    _scope_match(row, target_bot_id, target_group_id)
                    and str(row.get("outcome_id") or "") == target_outcome_id
                ):
                    try:
                        return NegativeOutcomeApplyResult(
                            applied=False,
                            outcome_id=target_outcome_id,
                            bot_id=target_bot_id,
                            group_id=target_group_id,
                            created_at=int(row.get("created_at") or 0),
                            decisions=[
                                SourceDecision.model_validate(item)
                                for item in (row.get("decisions") or [])
                                if isinstance(item, dict)
                            ],
                            blacklist_phrases=list(row.get("blacklist_phrases") or []),
                        )
                    except (TypeError, ValueError):
                        return NegativeOutcomeApplyResult(
                            applied=False,
                            outcome_id=target_outcome_id,
                            bot_id=target_bot_id,
                            group_id=target_group_id,
                            created_at=0,
                        )
            needs_leading_newline = False
            if path.exists() and path.stat().st_size > 0:
                with path.open("rb") as existing:
                    existing.seek(-1, os.SEEK_END)
                    needs_leading_newline = existing.read(1) != b"\n"
            with path.open("a", encoding="utf-8") as handle:
                if needs_leading_newline:
                    handle.write("\n")
                handle.write(line)
    except OSError:
        log_rate_limited(
            logger,
            "warning",
            "llm.injection_governance.append_failed",
            "injection governance outcome append failed",
        )
        return NegativeOutcomeApplyResult(
            applied=False,
            outcome_id=target_outcome_id,
            bot_id=target_bot_id,
            group_id=target_group_id,
            created_at=created_at,
            decisions=decisions,
            blacklist_phrases=blacklist_phrases,
        )
    return NegativeOutcomeApplyResult(
        applied=True,
        outcome_id=target_outcome_id,
        bot_id=target_bot_id,
        group_id=target_group_id,
        created_at=created_at,
        decisions=decisions,
        blacklist_phrases=blacklist_phrases,
    )


def effective_source_score(
    bot_id: int,
    group_id: int,
    kind: str,
    source_id: str,
    *,
    now: int | None = None,
) -> float:
    target_kind = str(kind or "").strip().lower()
    target_source_id = str(source_id or "").strip()
    current = int(now) if now is not None else int(time.time())
    total = 0.0
    for row in _load_outcomes():
        if not _scope_match(row, bot_id, group_id) or row.get("undo"):
            continue
        try:
            age = max(0, current - int(row.get("created_at") or 0))
        except (TypeError, ValueError):
            continue
        decay = 0.5 ** (age / _HALF_LIFE_SEC)
        for decision in row.get("decisions") or []:
            if not isinstance(decision, dict):
                continue
            if str(decision.get("kind") or "").strip().lower() != target_kind:
                continue
            if str(decision.get("source_id") or "") != target_source_id:
                continue
            try:
                total += float(decision.get("score") or 0.0) * decay
            except (TypeError, ValueError):
                continue
    return round(total, 4)


def _ambient_blacklist(bot_id: int, group_id: int) -> list[str]:
    return _ambient_blacklist_from_rows(_load_outcomes(), bot_id, group_id)


def _ambient_blacklist_from_rows(rows: list[dict[str, Any]], bot_id: int, group_id: int) -> list[str]:
    phrases: list[str] = []
    for row in rows:
        if not _scope_match(row, bot_id, group_id) or row.get("undo"):
            continue
        for phrase in row.get("blacklist_phrases") or []:
            if isinstance(phrase, str) and phrase and phrase not in phrases:
                phrases.append(phrase)
    return phrases


def _turn_text(turn: Any) -> str:
    if isinstance(turn, dict):
        for key in ("content", "text", "plain_text"):
            value = turn.get(key)
            if value:
                return str(value)
        return ""
    for key in ("content", "plain_text", "text"):
        value = getattr(turn, key, None)
        if value:
            return str(value)
    return ""


def filter_ambient_turns(bot_id: int, group_id: int, turns: list[Any]) -> list[Any]:
    blacklist = _ambient_blacklist(bot_id, group_id)
    if not blacklist:
        return list(turns)
    filtered: list[Any] = []
    for turn in turns:
        text = _turn_text(turn)
        if any(phrase in text for phrase in blacklist):
            continue
        filtered.append(turn)
    return filtered


def undo_negative_outcome_status(
    *,
    outcome_id: str,
    bot_id: int,
    group_id: int,
    now: int | None = None,
) -> Literal["undone", "missing", "storage_error"]:
    target_outcome_id = str(outcome_id or "").strip()
    if not target_outcome_id:
        return "missing"
    target_bot_id = int(bot_id)
    target_group_id = int(group_id)
    undone_at = int(now) if now is not None else int(time.time())
    path = outcomes_path(create=False)
    try:
        rows = list(_iter_outcomes(path))
        target = next(
            (
                row
                for row in rows
                if _scope_match(row, target_bot_id, target_group_id)
                and str(row.get("outcome_id") or "") == target_outcome_id
            ),
            None,
        )
        if target is None:
            return "missing"
        if target.get("undo"):
            return "undone"
        with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
            rows = list(_iter_outcomes(path))
            target = None
            for row in rows:
                if (
                    _scope_match(row, target_bot_id, target_group_id)
                    and str(row.get("outcome_id") or "") == target_outcome_id
                ):
                    target = row
                    break
            if target is None:
                return "missing"
            if target.get("undo"):
                return "undone"
            target["undo"] = True
            target["undone_at"] = undone_at
            effects = target.get("effects")
            if isinstance(effects, dict):
                for kind, effect in effects.items():
                    if isinstance(effect, dict):
                        effects[kind] = {"state": "cancelled"}
            body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
            atomic_write_text(path, body)
    except OSError:
        log_rate_limited(
            logger,
            "warning",
            "llm.injection_governance.undo_failed",
            "injection governance outcome undo failed",
        )
        return "storage_error"
    return "undone"


def undo_negative_outcome(
    *,
    outcome_id: str,
    bot_id: int,
    group_id: int,
    now: int | None = None,
) -> bool:
    return (
        undo_negative_outcome_status(
            outcome_id=outcome_id,
            bot_id=bot_id,
            group_id=group_id,
            now=now,
        )
        == "undone"
    )


def _injection_governance_payload(
    rows: list[dict[str, Any]],
    *,
    bot_id: int,
    group_id: int,
    now: int | None = None,
) -> dict[str, Any]:
    scope = [row for row in rows if _scope_match(row, bot_id, group_id)]
    current = int(now) if now is not None else int(time.time())
    score_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for row in scope:
        try:
            created_at = int(row.get("created_at") or 0)
        except (TypeError, ValueError):
            continue
        for decision in row.get("decisions") or []:
            if not isinstance(decision, dict):
                continue
            kind = str(decision.get("kind") or "").strip()
            source_id = str(decision.get("source_id") or "").strip()
            key = (kind, source_id)
            entry = score_rows.setdefault(
                key,
                {
                    "kind": kind,
                    "source_id": source_id,
                    "score": 0.0,
                    "audit_only": bool(decision.get("audit_only")),
                    "events": 0,
                },
            )
            if row.get("undo"):
                continue
            try:
                score = float(decision.get("score") or 0.0)
            except (TypeError, ValueError):
                continue
            age = max(0, current - created_at)
            entry["score"] += score * (0.5 ** (age / _HALF_LIFE_SEC))
            entry["events"] += 1
    sources = [
        {
            "kind": entry["kind"],
            "source_id": entry["source_id"],
            "score": round(entry["score"], 4),
            "audit_only": entry["audit_only"],
            "events": entry["events"],
        }
        for entry in score_rows.values()
    ]
    return {
        "bot_id": int(bot_id),
        "group_id": int(group_id),
        "outcomes": scope,
        "sources": sources,
        "ambient_blacklist": _ambient_blacklist_from_rows(rows, bot_id, group_id),
    }


def list_injection_governance_status(
    *,
    bot_id: int,
    group_id: int,
    now: int | None = None,
) -> tuple[Literal["ok", "storage_error"], dict[str, Any]]:
    path = outcomes_path(create=False)
    try:
        rows = list(_iter_outcomes(path))
    except OSError:
        log_rate_limited(
            logger,
            "warning",
            "llm.injection_governance.read_failed",
            "injection governance ledger read failed: [{}]",
            path,
        )
        return "storage_error", {}
    return "ok", _injection_governance_payload(rows, bot_id=bot_id, group_id=group_id, now=now)


def list_injection_governance(*, bot_id: int, group_id: int, now: int | None = None) -> dict[str, Any]:
    status, payload = list_injection_governance_status(bot_id=bot_id, group_id=group_id, now=now)
    if status == "ok":
        return payload
    return _injection_governance_payload([], bot_id=bot_id, group_id=group_id, now=now)
