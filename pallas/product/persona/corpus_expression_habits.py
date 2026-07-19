from __future__ import annotations

from typing import Any

from pallas.product.persona.affect_lexicon import load_affect_lexicon, punct_aggression_score
from pallas.product.persona.prompt_guard import sanitize_prompt_literal


def pick_corpus_expression_candidates(rows: list[dict[str, Any]], *, limit: int = 3) -> list[str]:
    scored: list[tuple[int, str]] = []
    for row in rows:
        text = sanitize_prompt_literal(str(row.get("text") or "").strip(), max_len=24)
        if not text or "[CQ:" in text:
            continue
        if len(text) <= 1 and not text.isalnum():
            continue
        count = int(row.get("count") or 0)
        if len(text) > 12:
            continue
        scored.append((count, text))

    scored.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
    out: list[str] = []
    seen: set[str] = set()
    for _count, text in scored:
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= max(1, int(limit)):
            break
    return out


def pick_topical_corpus_expression_candidates(
    rows: list[dict[str, Any]],
    *,
    trigger_keywords: list[str],
    limit: int = 3,
) -> list[str]:
    normalized_keywords = [
        sanitize_prompt_literal(str(item or "").strip(), max_len=24)
        for item in trigger_keywords
        if sanitize_prompt_literal(str(item or "").strip(), max_len=24)
    ]
    if not normalized_keywords:
        return []

    topical_rows: list[dict[str, Any]] = []
    for row in rows:
        row_keywords = str(row.get("keywords") or "").strip()
        if not row_keywords:
            continue
        if not any(keyword in row_keywords for keyword in normalized_keywords):
            continue
        topical_rows.append(row)
    return pick_corpus_expression_candidates(topical_rows, limit=limit)


def infer_expression_affect_stance(text: str) -> str:
    plain = sanitize_prompt_literal(str(text or "").strip(), max_len=64).lower()
    if not plain:
        return "neutral"

    lex = load_affect_lexicon()
    if any(token in plain for token in lex["polite"]):
        return "warm"
    complain_markers = (
        "太",
        "离谱",
        "黑了",
        "真的黑",
        "什么鬼",
        "搞什么",
        "有病",
        "逆天",
        "绷不住",
        "服了",
        "抽卡",
        "有点狠",
    )
    if (
        any(token in plain for token in lex["harsh"])
        or punct_aggression_score(plain) >= 0.2
        or any(token in plain for token in complain_markers)
    ):
        return "complain"
    if any(token in plain for token in ("确实", "也是", "对啊", "行啊", "是啊", "还真是")):
        return "echo"
    return "neutral"


def pick_affect_aligned_corpus_expression_candidates(
    rows: list[dict[str, Any]],
    *,
    trigger_keywords: list[str],
    target_stance: str,
    limit: int = 3,
) -> list[str]:
    stance = str(target_stance or "").strip()
    if not stance:
        return []
    topical_rows: list[dict[str, Any]] = []
    normalized_keywords = [
        sanitize_prompt_literal(str(item or "").strip(), max_len=24)
        for item in trigger_keywords
        if sanitize_prompt_literal(str(item or "").strip(), max_len=24)
    ]
    for row in rows:
        row_keywords = str(row.get("keywords") or "").strip()
        if normalized_keywords and row_keywords and not any(keyword in row_keywords for keyword in normalized_keywords):
            continue
        if infer_expression_affect_stance(str(row.get("text") or "")) != stance:
            continue
        topical_rows.append(row)
    return pick_corpus_expression_candidates(topical_rows, limit=limit)
