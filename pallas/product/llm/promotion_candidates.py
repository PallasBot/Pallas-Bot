"""Promotion candidate storage and approval gate for repeater writeback."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Literal

from pallas.core.foundation.db.modules import Answer, Context
from pallas.product.llm.kernel.feedback_models import PromotionCandidate
from pallas.product.llm.repeater_feedback import (
    LlmRepeaterFeedbackEntry,
    effective_feedback_reply_text,
    feedback_base_dir,
    is_reply_safe_for_auto_promote,
    list_group_feedback_entries,
    promotion_allowed,
)

PROMOTION_SUPPORT_THRESHOLD = 2
AUTO_PROMOTE_SUPPORT_THRESHOLD = 3
ResolveAction = Literal["promote", "reject"]


def promotion_candidates_path():
    path = feedback_base_dir() / "candidates.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def build_candidate_id(*, group_id: int, trigger_text: str, reply_text: str) -> str:
    trigger_kw = _chat_keywords(trigger_text, group_id=int(group_id))
    key = f"{int(group_id)}:{trigger_kw}:{str(reply_text or '').strip()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _iter_candidates(path):
    with path.open(encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                yield PromotionCandidate.model_validate(payload)
            except (TypeError, ValueError):
                continue


def _load_candidates_index() -> dict[str, PromotionCandidate]:
    path = promotion_candidates_path()
    if not path.exists():
        return {}
    rows: dict[str, PromotionCandidate] = {}
    for item in _iter_candidates(path):
        rows[str(item.candidate_id).strip()] = item
    return rows


def _write_candidates_index(rows: dict[str, PromotionCandidate]) -> None:
    from pallas.core.foundation.fs_lock import atomic_write_text, interprocess_file_lock

    path = promotion_candidates_path()
    ordered = sorted(rows.values(), key=lambda item: (-int(item.last_seen_at), item.candidate_id))
    body = "".join(json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n" for item in ordered)
    with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
        atomic_write_text(path, body)


def feedback_entry_support_weight(item: LlmRepeaterFeedbackEntry) -> int:
    if str(item.corrected_reply_text or "").strip():
        return 2
    return 1


def reply_support_weight(reply_entries: list[LlmRepeaterFeedbackEntry]) -> tuple[int, bool]:
    weight = 0
    has_correction = False
    for item in reply_entries:
        weight += feedback_entry_support_weight(item)
        if str(item.corrected_reply_text or "").strip():
            has_correction = True
    return weight, has_correction


def _aggregate_trigger_reply_support(
    entries: list[LlmRepeaterFeedbackEntry],
) -> dict[tuple[str, str], list[LlmRepeaterFeedbackEntry]]:
    grouped: dict[tuple[str, str], list[LlmRepeaterFeedbackEntry]] = {}
    for item in entries:
        if not item.eligible_for_bias:
            continue
        reply_text = effective_feedback_reply_text(item)
        if not reply_text:
            continue
        from pallas.product.llm.corpus_contamination import is_llm_learning_safe

        if not is_llm_learning_safe(str(item.user_text or "")) or not is_reply_safe_for_auto_promote(
            reply_text,
            trigger_text=str(item.user_text or ""),
        ):
            continue
        trigger_kw = _chat_keywords(str(item.user_text or "").strip(), group_id=int(item.group_id))
        if not trigger_kw:
            continue
        grouped.setdefault((trigger_kw, reply_text), []).append(item)
    return grouped


def is_auto_promote_eligible(candidate: PromotionCandidate) -> bool:
    if candidate.promoted or str(candidate.rejected_reason or "").strip():
        return False
    if not is_reply_safe_for_auto_promote(
        candidate.reply_text,
        trigger_text=str(candidate.trigger_text or ""),
    ):
        return False
    if not str(candidate.trigger_text or "").strip():
        return False
    support = int(candidate.support_count or 0)
    if support >= AUTO_PROMOTE_SUPPORT_THRESHOLD:
        return True
    return support >= PROMOTION_SUPPORT_THRESHOLD and bool(candidate.correction_backed)


def refresh_promotion_candidates_for_group(*, group_id: int, limit: int = 200) -> list[PromotionCandidate]:
    if not promotion_allowed():
        return []
    entries = list_group_feedback_entries(group_id=int(group_id), limit=max(1, int(limit)))
    grouped = _aggregate_trigger_reply_support(entries)
    rows = _load_candidates_index()
    changed = False
    created: list[PromotionCandidate] = []
    for (trigger_kw, reply_text), reply_entries in grouped.items():
        support_count, correction_backed = reply_support_weight(reply_entries)
        if support_count < PROMOTION_SUPPORT_THRESHOLD:
            continue
        reply_entries.sort(key=lambda item: int(item.created_at))
        latest = reply_entries[-1]
        candidate_id = build_candidate_id(
            group_id=int(group_id),
            trigger_text=str(latest.user_text or trigger_kw),
            reply_text=reply_text,
        )
        existing = rows.get(candidate_id)
        if existing is not None and (existing.promoted or str(existing.rejected_reason or "").strip()):
            continue
        candidate = PromotionCandidate(
            candidate_id=candidate_id,
            group_id=int(group_id),
            trigger_text=str(latest.user_text or "").strip(),
            reply_text=reply_text,
            support_count=support_count,
            correction_backed=correction_backed,
            last_seen_at=int(latest.created_at or time.time()),
            promoted=bool(existing.promoted) if existing is not None else False,
            rejected_reason=str(existing.rejected_reason or "") if existing is not None else "",
            behavior_scene=str(latest.behavior_scene or "").strip(),
            source_request_id=str(latest.request_id or "").strip(),
        )
        if existing is None or candidate.model_dump() != existing.model_dump():
            rows[candidate_id] = candidate
            changed = True
            created.append(candidate)
    if changed:
        _write_candidates_index(rows)
    schedule_auto_promote_for_group(int(group_id))
    return created


def list_promotion_candidates(
    *,
    group_id: int,
    limit: int = 50,
    include_resolved: bool = False,
    refresh: bool = True,
) -> list[PromotionCandidate]:
    if refresh and promotion_allowed():
        refresh_promotion_candidates_for_group(group_id=int(group_id), limit=max(50, int(limit) * 4))
    rows = [
        item
        for item in _load_candidates_index().values()
        if int(item.group_id) == int(group_id)
        and (include_resolved or (not item.promoted and not str(item.rejected_reason or "").strip()))
    ]
    rows.sort(key=lambda item: (-int(item.support_count), -int(item.last_seen_at), item.candidate_id))
    return rows[: max(1, int(limit))]


def count_pending_promotion_candidates(*, group_id: int) -> int:
    return len(list_promotion_candidates(group_id=int(group_id), limit=200, include_resolved=False, refresh=True))


def resolve_promotion_candidate(
    candidate_id: str,
    *,
    action: ResolveAction,
    reason: str = "",
) -> PromotionCandidate | None:
    key = str(candidate_id or "").strip()
    if not key:
        return None
    rows = _load_candidates_index()
    item = rows.get(key)
    if item is None:
        return None
    if action == "promote":
        if not promotion_allowed():
            return None
        item.promoted = True
        item.rejected_reason = ""
    elif action == "reject":
        item.promoted = False
        item.rejected_reason = str(reason or "rejected").strip() or "rejected"
    else:
        return None
    rows[key] = item
    _write_candidates_index(rows)
    return item


def _chat_keywords(text: str, *, group_id: int) -> str:
    try:
        from packages.repeater.model import ChatData

        chat = ChatData(
            group_id=int(group_id),
            user_id=0,
            raw_message=str(text or "").strip(),
            plain_text=str(text or "").strip(),
            time=0,
            bot_id=0,
        )
        return str(chat.keywords or "").strip() or str(text or "").strip()
    except Exception:
        return str(text or "").strip()


async def writeback_promotion_candidate(candidate: PromotionCandidate) -> PromotionCandidate:
    from pallas.core.foundation.db import init_postgresql_db, is_postgresql_backend
    from pallas.core.foundation.db.context_repo_access import get_shared_context_repository
    from pallas.core.foundation.db.repository_pg import is_pg_initialized

    if is_postgresql_backend() and not is_pg_initialized():
        await init_postgresql_db()

    now = int(time.time())
    trigger_keywords = _chat_keywords(candidate.trigger_text, group_id=int(candidate.group_id))
    answer_keywords = _chat_keywords(candidate.reply_text, group_id=int(candidate.group_id))
    if not trigger_keywords or not candidate.reply_text:
        candidate.writeback_status = "failed"
        candidate.writeback_message = "empty trigger or reply"
        candidate.writeback_at = now
        return candidate
    from pallas.product.llm.corpus_contamination import is_corpus_learn_safe

    if not is_corpus_learn_safe(str(candidate.reply_text)):
        candidate.writeback_status = "failed"
        candidate.writeback_message = "corpus contamination guard"
        candidate.writeback_at = now
        return candidate
    repo = get_shared_context_repository()
    learn_answer = getattr(repo, "learn_answer", None)
    if callable(learn_answer):
        await learn_answer(
            keywords=trigger_keywords,
            group_id=int(candidate.group_id),
            answer_keywords=answer_keywords,
            answer_time=now,
            message=str(candidate.reply_text),
            append_on_existing=True,
        )
    elif await repo.context_exists_by_keywords(trigger_keywords):
        await repo.upsert_answer(
            keywords=trigger_keywords,
            group_id=int(candidate.group_id),
            answer_keywords=answer_keywords,
            answer_time=now,
            message=str(candidate.reply_text),
            append_on_existing=True,
        )
    else:
        context = Context.model_construct(
            keywords=trigger_keywords,
            time=now,
            trigger_count=1,
            answers=[
                Answer(
                    keywords=answer_keywords,
                    group_id=int(candidate.group_id),
                    count=1,
                    time=now,
                    messages=[str(candidate.reply_text)],
                )
            ],
            ban=[],
            clear_time=0,
        )
        await repo.insert(context)
    candidate.writeback_status = "written"
    candidate.writeback_message = "context_repository"
    candidate.writeback_at = now
    return candidate


async def resolve_promotion_candidate_with_writeback(
    candidate_id: str,
    *,
    action: ResolveAction,
    reason: str = "",
) -> PromotionCandidate | None:
    item = resolve_promotion_candidate(candidate_id, action=action, reason=reason)
    if item is None or action != "promote":
        return item
    try:
        updated = await writeback_promotion_candidate(item)
        rows = _load_candidates_index()
        rows[str(updated.candidate_id).strip()] = updated
        _write_candidates_index(rows)
        return updated
    except Exception as exc:  # noqa: BLE001
        item.writeback_status = "failed"
        item.writeback_message = str(exc)
        item.writeback_at = int(time.time())
        rows = _load_candidates_index()
        rows[str(item.candidate_id).strip()] = item
        _write_candidates_index(rows)
        return item


def schedule_auto_promote_for_group(group_id: int) -> None:
    if not promotion_allowed() or int(group_id) <= 0:
        return
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(auto_promote_eligible_candidates_for_group(group_id=int(group_id)))


async def auto_promote_eligible_candidates_for_group(*, group_id: int) -> list[PromotionCandidate]:
    if not promotion_allowed():
        return []
    promoted: list[PromotionCandidate] = []
    rows = list_promotion_candidates(group_id=int(group_id), refresh=False, include_resolved=False)
    for candidate in rows:
        if not is_auto_promote_eligible(candidate):
            continue
        updated = await resolve_promotion_candidate_with_writeback(candidate.candidate_id, action="promote")
        if updated is None or updated.writeback_status != "written":
            continue
        updated.writeback_message = "auto_promoted"
        rows_index = _load_candidates_index()
        rows_index[str(updated.candidate_id).strip()] = updated
        _write_candidates_index(rows_index)
        promoted.append(updated)
    return promoted


def note_feedback_entry_for_promotion(entry: LlmRepeaterFeedbackEntry) -> None:
    if not promotion_allowed():
        return
    if int(entry.group_id or 0) <= 0:
        return
    refresh_promotion_candidates_for_group(group_id=int(entry.group_id))
