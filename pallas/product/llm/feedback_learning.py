"""LLM 反哺样本：衰减、场景分桶、负样本沉淀、向量近似与塑形联动。"""

from __future__ import annotations

import re
import time
from collections import Counter
from operator import itemgetter

from pallas.product.llm.config import resolve_llm_vector_retrieve
from pallas.product.llm.feedback_chat_hint import correction_matches_query
from pallas.product.llm.repeater_feedback import (
    LlmRepeaterFeedbackEntry,
    effective_feedback_reply_text,
    list_group_feedback_entries,
)

FEEDBACK_DECAY_HALF_LIFE_SEC = 14 * 86400
FEEDBACK_MAX_AGE_SEC = 90 * 86400
FEEDBACK_SCENE_MISMATCH_WEIGHT = 0.35
FEEDBACK_SCENE_UNKNOWN_WEIGHT = 0.75
VECTOR_MATCH_MIN_SCORE = 72
VECTOR_MATCH_LIMIT = 3
PERSONA_SHAPING_WRITEBACK_MAX_LEN = 24

_KAOMOJI_SUFFIX_RE = re.compile(r"\(\*[^)]{1,16}\*\)\s*$")


def feedback_entry_age_weight(*, created_at: int, now: int | None = None) -> float:
    ts = int(created_at or 0)
    if ts <= 0:
        return 1.0
    age = max(0, int(now or time.time()) - ts)
    if age >= FEEDBACK_MAX_AGE_SEC:
        return 0.0
    return 0.5 ** (age / FEEDBACK_DECAY_HALF_LIFE_SEC)


def scene_match_weight(*, entry_scene: str, active_scene: str) -> float:
    active = str(active_scene or "").strip()
    scene = str(entry_scene or "").strip()
    if not active:
        return 1.0
    if not scene:
        return FEEDBACK_SCENE_UNKNOWN_WEIGHT
    if scene == active:
        return 1.0
    return FEEDBACK_SCENE_MISMATCH_WEIGHT


def feedback_entry_effective_weight(
    item: LlmRepeaterFeedbackEntry,
    *,
    active_scene: str = "",
    now: int | None = None,
) -> float:
    if not item.eligible_for_bias:
        return 0.0
    return feedback_entry_age_weight(created_at=int(item.created_at), now=now) * scene_match_weight(
        entry_scene=str(item.behavior_scene or ""),
        active_scene=active_scene,
    )


def compute_penalized_replies(rows: list[LlmRepeaterFeedbackEntry]) -> list[str]:
    bad_counter: Counter[str] = Counter()
    kaomoji_counter = 0
    for item in rows:
        if item.eligible_for_bias:
            continue
        snippet = str(item.reply_text or "").strip()
        if snippet:
            bad_counter[snippet] += 1
        if _KAOMOJI_SUFFIX_RE.search(str(item.reply_text or "")):
            kaomoji_counter += 1
    penalized = {text for text, count in bad_counter.items() if count >= 2}
    if kaomoji_counter >= 2:
        for item in rows:
            reply = str(item.reply_text or "").strip()
            if reply and _KAOMOJI_SUFFIX_RE.search(reply):
                penalized.add(reply)
    return sorted(penalized)


def weighted_reply_counter(
    rows: list[LlmRepeaterFeedbackEntry],
    *,
    active_scene: str = "",
    now: int | None = None,
) -> Counter[str]:
    counter: Counter[str] = Counter()
    for item in rows:
        reply = effective_feedback_reply_text(item)
        if not reply:
            continue
        weight = feedback_entry_effective_weight(item, active_scene=active_scene, now=now)
        if weight <= 0.0:
            continue
        from pallas.product.llm.corpus_contamination import is_feedback_reply_collectable

        if not is_feedback_reply_collectable(reply):
            continue
        counter[reply] += weight
    return counter


def find_trigger_matched_replies(
    *,
    rows: list[LlmRepeaterFeedbackEntry],
    user_text: str,
    active_scene: str = "",
    limit: int = 3,
    now: int | None = None,
) -> list[str]:
    query = str(user_text or "").strip()
    if not query:
        return []
    scored: list[tuple[float, str]] = []
    seen: set[str] = set()
    for item in reversed(rows):
        if not str(item.user_text or "").strip():
            continue
        if not correction_matches_query(item.user_text, query):
            continue
        reply = effective_feedback_reply_text(item)
        if not reply or reply in seen:
            continue
        weight = feedback_entry_effective_weight(item, active_scene=active_scene, now=now)
        if weight <= 0.0:
            continue
        seen.add(reply)
        scored.append((weight, reply))
    scored.sort(key=itemgetter(0), reverse=True)
    return [text for _, text in scored[: max(1, int(limit))]]


def find_semantic_matched_replies(
    *,
    rows: list[LlmRepeaterFeedbackEntry],
    user_text: str,
    active_scene: str = "",
    limit: int = VECTOR_MATCH_LIMIT,
    now: int | None = None,
) -> list[str]:
    query = str(user_text or "").strip()
    if not query:
        return []
    mode = resolve_llm_vector_retrieve()
    if mode not in ("embedding", "hybrid", "vector"):
        return []
    candidates: list[tuple[float, str, str]] = []
    seen: set[str] = set()
    for item in rows:
        trigger = str(item.user_text or "").strip()
        reply = effective_feedback_reply_text(item)
        if not trigger or not reply or reply in seen:
            continue
        weight = feedback_entry_effective_weight(item, active_scene=active_scene, now=now)
        if weight <= 0.0:
            continue
        seen.add(reply)
        candidates.append((weight, trigger, reply))
    if not candidates:
        return []
    from pallas.product.llm.knowledge.embedding_client import fetch_embeddings_sync
    from pallas.product.llm.knowledge.embedding_score import embedding_relevance_score

    texts = [query] + [trigger for _, trigger, _ in candidates]
    vectors = fetch_embeddings_sync(texts)
    if not vectors or len(vectors) != len(texts):
        return []
    query_vec = vectors[0]
    scored: list[tuple[float, str]] = []
    for idx, (weight, _trigger, reply) in enumerate(candidates, start=1):
        score = embedding_relevance_score(query_vec, vectors[idx])
        if score < VECTOR_MATCH_MIN_SCORE:
            continue
        scored.append((weight * (score / 100.0), reply))
    scored.sort(key=itemgetter(0), reverse=True)
    ordered: list[str] = []
    seen_reply: set[str] = set()
    for _, reply in scored:
        if reply in seen_reply:
            continue
        seen_reply.add(reply)
        ordered.append(reply)
        if len(ordered) >= max(1, int(limit)):
            break
    return ordered


def resolve_persona_shaping_writeback_max_len() -> int | None:
    from pallas.product.llm.config import get_llm_config
    from pallas.product.llm.kernel.memory_governance import can_read_behavioral_learning

    cfg = get_llm_config()
    if not cfg.llm_chat_enabled or not can_read_behavioral_learning():
        return None
    return PERSONA_SHAPING_WRITEBACK_MAX_LEN


def is_reply_safe_for_shaped_writeback(reply_text: str) -> bool:
    max_len = resolve_persona_shaping_writeback_max_len()
    if max_len is None:
        return True
    plain = str(reply_text or "").strip()
    if not plain:
        return False
    if len(plain) > max_len:
        return False
    if _KAOMOJI_SUFFIX_RE.search(plain):
        return False
    return True


def summarize_learning_effectiveness(*, group_id: int, window_sec: int = 7 * 86400) -> dict[str, int | float]:
    from packages.repeater.opportunity_trace import read_recent_repeater_opportunity_trace

    now = int(time.time())
    cutoff = now - max(3600, int(window_sec))
    rows = read_recent_repeater_opportunity_trace(limit=500)
    bias_hits = 0
    auto_promotes = 0
    total_replies = 0
    for row in rows:
        if int(row.get("group_id") or 0) != int(group_id):
            continue
        if str(row.get("kind") or "") != "repeater_reply_bundle":
            continue
        ts = int(row.get("ts") or 0)
        if ts < cutoff:
            continue
        total_replies += 1
        mult = float(row.get("feedback_bias_multiplier") or 1.0)
        if mult > 1.001:
            bias_hits += 1
    from pallas.product.llm.promotion_candidates import list_promotion_candidates

    for item in list_promotion_candidates(group_id=int(group_id), limit=200, include_resolved=True, refresh=False):
        if str(item.writeback_message or "") == "auto_promoted" and int(item.writeback_at or 0) >= cutoff:
            auto_promotes += 1
    hit_rate = (bias_hits / total_replies) if total_replies else 0.0
    return {
        "window_sec": int(window_sec),
        "repeater_reply_count": total_replies,
        "feedback_bias_hit_count": bias_hits,
        "feedback_bias_hit_rate": round(hit_rate, 4),
        "auto_promote_count": auto_promotes,
    }


def build_feedback_bias_snapshot_data(
    *,
    group_id: int,
    limit: int = 50,
    user_text: str = "",
    behavior_scene: str = "",
) -> dict:
    from pallas.product.llm.kernel.feedback_models import FeedbackBiasSnapshot
    from pallas.product.llm.kernel.memory_governance import can_promote_writeback
    from pallas.product.llm.promotion_candidates import count_pending_promotion_candidates

    all_rows = list_group_feedback_entries(group_id=int(group_id), limit=max(1, int(limit)))
    now = int(time.time())
    rows = [item for item in all_rows if item.eligible_for_bias]
    weighted = weighted_reply_counter(rows, active_scene=behavior_scene, now=now)
    top_replies = [text for text, _ in weighted.most_common(3)]
    scene_counter = Counter(
        item.behavior_scene
        for item in rows
        if item.behavior_scene and feedback_entry_effective_weight(item, active_scene=behavior_scene, now=now) > 0
    )
    scenes = [text for text, _ in scene_counter.most_common(5)]
    matched_replies = find_trigger_matched_replies(
        rows=rows,
        user_text=user_text,
        active_scene=behavior_scene,
        limit=3,
        now=now,
    )
    semantic_matched_replies = find_semantic_matched_replies(
        rows=rows,
        user_text=user_text,
        active_scene=behavior_scene,
        limit=VECTOR_MATCH_LIMIT,
        now=now,
    )
    penalized_replies = compute_penalized_replies(all_rows)
    promotion_candidate_count = 0
    if can_promote_writeback():
        promotion_candidate_count = count_pending_promotion_candidates(group_id=int(group_id))
    learning_stats = summarize_learning_effectiveness(group_id=int(group_id))
    active_count = sum(
        1 for item in rows if feedback_entry_effective_weight(item, active_scene=behavior_scene, now=now) > 0.05
    )
    snapshot = FeedbackBiasSnapshot(
        count=active_count,
        top_replies=top_replies,
        matched_replies=matched_replies,
        semantic_matched_replies=semantic_matched_replies,
        penalized_replies=penalized_replies,
        scenes=scenes,
        promotion_candidate_count=promotion_candidate_count,
        learning_stats=learning_stats,
    )
    return snapshot.model_dump(mode="json")


def feedback_bias_multiplier_for_text(
    text: str,
    *,
    feedback_snapshot: dict | None,
    max_multiplier: float = 1.18,
    matched_multiplier: float = 1.18,
    semantic_multiplier: float = 1.12,
    top_multiplier: float = 1.08,
    partial_multiplier: float = 1.05,
    penalty_multiplier: float = 0.45,
    min_count: int = 2,
    matched_min_count: int = 1,
) -> float:
    plain = str(text or "").strip()
    if not plain or not isinstance(feedback_snapshot, dict):
        return 1.0
    if len(plain) > 32:
        return 1.0
    penalized = {
        str(item).strip() for item in list(feedback_snapshot.get("penalized_replies") or []) if str(item).strip()
    }
    if plain in penalized:
        return penalty_multiplier
    count = int(feedback_snapshot.get("count") or 0)
    mult = 1.0
    matched_replies = {
        str(item).strip() for item in list(feedback_snapshot.get("matched_replies") or []) if str(item).strip()
    }
    if matched_replies and count >= matched_min_count and plain in matched_replies:
        mult = max(mult, matched_multiplier)
    semantic_replies = {
        str(item).strip() for item in list(feedback_snapshot.get("semantic_matched_replies") or []) if str(item).strip()
    }
    if semantic_replies and count >= matched_min_count and plain in semantic_replies:
        mult = max(mult, semantic_multiplier)
    if count >= min_count:
        top_replies = {
            str(item).strip() for item in list(feedback_snapshot.get("top_replies") or []) if str(item).strip()
        }
        if plain in top_replies:
            mult = max(mult, top_multiplier)
        else:
            for sample in top_replies:
                if len(sample) < 3:
                    continue
                if sample in plain or plain in sample:
                    mult = max(mult, partial_multiplier)
                    break
    return min(max_multiplier, mult) if mult > 1.0 else mult
