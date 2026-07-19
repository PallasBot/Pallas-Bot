from __future__ import annotations

from math import log1p
from operator import itemgetter

from pallas.product.persona.corpus_expression_habits import infer_expression_affect_stance
from pallas.product.persona.dynamic_expression import (
    clean_expression_reference_text,
    is_usable_expression_reference,
)

RECENT_LIVE_SOURCE = "recent_live"
REPEATER_SOURCE = "repeater"
ANSWER_SOURCE = "answers"


def allow_recent_stance_backfill(target_stance: str, candidate_text: str) -> bool:
    candidate_stance = infer_expression_affect_stance(candidate_text)
    if target_stance == "complain":
        return candidate_stance in {"complain", "echo", "neutral"}
    if target_stance == "warm":
        return candidate_stance in {"warm", "echo", "neutral"}
    if target_stance == "echo":
        return candidate_stance in {"echo", "neutral"}
    return candidate_stance == "neutral"


def has_topical_match(rows: list[dict[str, object]], trigger_keywords: list[str]) -> bool:
    normalized = [str(item or "").strip() for item in trigger_keywords if str(item or "").strip()]
    if not normalized:
        return False
    for row in rows:
        keywords = str(row.get("keywords") or "").strip()
        if keywords and any(keyword in keywords for keyword in normalized):
            return True
    return False


def topic_match_count(row: dict[str, object], trigger_keywords: list[str]) -> int:
    normalized = [str(item or "").strip() for item in trigger_keywords if str(item or "").strip()]
    if not normalized:
        return 0
    keywords = str(row.get("keywords") or "").strip()
    if not keywords:
        return 0
    return sum(1 for keyword in normalized if keyword in keywords)


def recent_hint_source_label(rows: list[dict[str, object]], trigger_keywords: list[str] | None = None) -> str:
    if any(str(row.get("source") or "") in {RECENT_LIVE_SOURCE, REPEATER_SOURCE} for row in rows):
        return "当前话题可参考本群最近常接的短句"
    if rows and (not trigger_keywords or has_topical_match(rows, trigger_keywords or [])):
        return "当前话题可参考本群常接的短句"
    return "本群常见短句可参考"


def ending_signature(text: str) -> str:
    plain = str(text or "").strip().rstrip("。！？!?~～…，,、 ")
    if not plain:
        return ""
    return plain[-2:]


def expression_shape_signature(text: str) -> str:
    plain = str(text or "").strip().rstrip("。！？!?~～…，,、 ")
    if not plain:
        return ""
    if plain.startswith("这也太") and plain.endswith("了吧"):
        return "这也太X了吧"
    for token in ("太黑了吧", "太离谱了吧", "有点狠", "那确实", "也不是不行"):
        if token in plain:
            return token
    return plain[-4:]


def topical_overlap(query_text: str, candidate_text: str) -> int:
    query = str(query_text or "").strip().rstrip("。！？!?~～…，,、 ")
    candidate = str(candidate_text or "").strip().rstrip("。！？!?~～…，,、 ")
    if not query or not candidate:
        return 0
    if candidate in query or query in candidate:
        return max(len(candidate), len(query))
    query_parts = {query[i : i + 2] for i in range(max(0, len(query) - 1))}
    candidate_parts = {candidate[i : i + 2] for i in range(max(0, len(candidate) - 1))}
    overlap = len(query_parts & candidate_parts)
    if overlap:
        return overlap
    return len(set(query) & set(candidate))


def score_expression_candidate(
    row: dict[str, object],
    *,
    target_stance: str,
    trigger_keywords: list[str],
    query_text: str,
    strong_near_field: bool,
    topical_mode: bool,
) -> tuple[float, int, int, int]:
    text = str(row.get("text") or "").strip()
    stance = infer_expression_affect_stance(text)
    source = str(row.get("source") or "")
    source_bonus = {
        RECENT_LIVE_SOURCE: 30.0,
        REPEATER_SOURCE: 24.0,
        ANSWER_SOURCE: 12.0,
    }.get(source, 0.0)
    if strong_near_field and target_stance == "complain" and stance != "complain":
        stance_bonus = -30.0
    elif target_stance == "complain" and stance == "echo" and not topical_mode:
        stance_bonus = 12.0
    elif target_stance == "complain" and stance == "echo":
        stance_bonus = 2.0
    else:
        stance_bonus = (
            20.0 if stance == target_stance else (8.0 if allow_recent_stance_backfill(target_stance, text) else -20.0)
        )
    topic_hits = int(row.get("topic_hits") or 0)
    count = int(row.get("count") or 0)
    time_score = int(row.get("time") or 0)
    topical_bonus = 0.0
    if topical_mode:
        topical_bonus = -12.0 if trigger_keywords else 0.0
    keywords = str(row.get("keywords") or "").strip()
    if trigger_keywords and keywords and any(keyword in keywords for keyword in trigger_keywords):
        topical_bonus = 10.0
    overlap_bonus = topical_overlap(query_text, text) * 1.5
    recency_bonus = 0.0
    if source in {RECENT_LIVE_SOURCE, REPEATER_SOURCE}:
        recency_bonus = log1p(max(0, time_score)) * 3.0
    return (
        source_bonus + stance_bonus + topical_bonus + overlap_bonus + recency_bonus + topic_hits * 4 + count * 1.5,
        topic_hits,
        time_score,
        count,
    )


def select_scored_expression_candidates(
    rows: list[dict[str, object]],
    *,
    target_stance: str,
    trigger_keywords: list[str],
    query_text: str,
    limit: int = 3,
    reference_min_len: int = 3,
    reference_min_cjk: int = 2,
) -> list[str]:
    normalized_keywords = [str(item or "").strip() for item in trigger_keywords if str(item or "").strip()]
    topical_rows: list[dict[str, object]] = []
    partial_rows: list[dict[str, object]] = []
    if normalized_keywords:
        for row in rows:
            hit_count = topic_match_count(row, normalized_keywords)
            if hit_count >= len(normalized_keywords):
                topical_rows.append(row)
            elif hit_count > 0:
                partial_rows.append(row)
    topical_mode = bool(topical_rows)
    candidate_rows = topical_rows or rows
    near_field_present = any(
        str(row.get("source") or "") in {RECENT_LIVE_SOURCE, REPEATER_SOURCE} for row in candidate_rows
    )
    strong_near_field = any(
        str(row.get("source") or "") in {RECENT_LIVE_SOURCE, REPEATER_SOURCE}
        and infer_expression_affect_stance(str(row.get("text") or "")) == target_stance
        for row in candidate_rows
    )
    scored: list[tuple[tuple[float, int, int, int], str]] = []
    for row in candidate_rows:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        stance = infer_expression_affect_stance(text)
        source = str(row.get("source") or "")
        if target_stance == "complain" and stance == "warm":
            continue
        if strong_near_field and target_stance == "complain":
            if stance in {"echo", "warm"}:
                continue
            if stance != "complain" and source == ANSWER_SOURCE:
                continue
        if near_field_present and source == ANSWER_SOURCE and stance == "echo":
            continue
        if (
            target_stance == "complain"
            and topical_mode
            and stance == "echo"
            and source not in {RECENT_LIVE_SOURCE, REPEATER_SOURCE}
        ):
            continue
        scored.append((
            score_expression_candidate(
                row,
                target_stance=target_stance,
                trigger_keywords=trigger_keywords,
                query_text=query_text,
                strong_near_field=strong_near_field,
                topical_mode=topical_mode,
            ),
            text,
        ))
    scored.sort(key=itemgetter(0), reverse=True)

    out: list[str] = []
    seen_text: set[str] = set()
    seen_endings: set[str] = set()
    seen_shapes: set[str] = set()
    for _score, text in scored:
        cleaned = clean_expression_reference_text(text)
        if not is_usable_expression_reference(
            cleaned,
            min_len=reference_min_len,
            min_cjk=reference_min_cjk,
        ):
            continue
        try:
            from pallas.product.llm.corpus_contamination import is_expression_reference_safe
        except Exception:
            pass
        else:
            if not is_expression_reference_safe(cleaned):
                continue
        text = cleaned
        if text in seen_text:
            continue
        ending = ending_signature(text)
        shape = expression_shape_signature(text)
        if ending and ending in seen_endings:
            continue
        if shape and shape in seen_shapes:
            continue
        seen_text.add(text)
        if ending:
            seen_endings.add(ending)
        if shape:
            seen_shapes.add(shape)
        out.append(text)
        if len(out) >= max(1, int(limit)):
            break
    if topical_mode and len(out) < max(1, int(limit)) and not near_field_present and partial_rows:
        supplemental_rows = select_scored_expression_candidates(
            partial_rows,
            target_stance=target_stance,
            trigger_keywords=[],
            query_text=query_text,
            limit=limit,
            reference_min_len=reference_min_len,
            reference_min_cjk=reference_min_cjk,
        )
        for text in supplemental_rows:
            cleaned = clean_expression_reference_text(text)
            if not is_usable_expression_reference(
                cleaned,
                min_len=reference_min_len,
                min_cjk=reference_min_cjk,
            ):
                continue
            text = cleaned
            if text in seen_text:
                continue
            ending = ending_signature(text)
            shape = expression_shape_signature(text)
            if ending and ending in seen_endings:
                continue
            if shape and shape in seen_shapes:
                continue
            seen_text.add(text)
            if ending:
                seen_endings.add(ending)
            if shape:
                seen_shapes.add(shape)
            out.append(text)
            if len(out) >= max(1, int(limit)):
                break
    return out
