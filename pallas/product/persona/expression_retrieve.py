"""Retrieve group expressions suitable for the current message."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pallas.product.llm.reply_variation import classify_repeated_opener
from pallas.product.persona.corpus_expression_habits import infer_expression_affect_stance
from pallas.product.persona.expression_bank import ExpressionEntry, list_group_expressions
from pallas.product.persona.prompt_guard import sanitize_prompt_literal

if TYPE_CHECKING:
    from collections.abc import Iterable

_WORD_RE = re.compile(r"[a-z0-9_]{2,}", re.IGNORECASE)


def _query_keywords(text: str) -> set[str]:
    plain = sanitize_prompt_literal(str(text or "").strip(), max_len=64).lower()
    keywords = set(_WORD_RE.findall(plain))
    cjk = "".join(char for char in plain if "\u4e00" <= char <= "\u9fff")
    keywords.update(cjk[index : index + 2] for index in range(max(0, len(cjk) - 1)))
    return keywords


def expression_opener_key(saying: str) -> str:
    opener = classify_repeated_opener(saying)
    if opener:
        return opener
    plain = sanitize_prompt_literal(str(saying or "").strip(), max_len=24)
    cjk = "".join(char for char in plain if "\u4e00" <= char <= "\u9fff")
    return cjk[:4] if len(cjk) >= 2 else plain[:4]


def score_expression_for_query(entry: ExpressionEntry, plain_text: str) -> int | None:
    """Return a relevance score, or None for entries that cannot be injected."""
    if entry.status == "rejected":
        return None

    score = 100 if entry.status == "active" else 50
    score += min(max(1, int(entry.support)), 10)

    target_stance = infer_expression_affect_stance(plain_text)
    entry_stance = str(entry.affect_hint or "").strip() or infer_expression_affect_stance(entry.saying)
    if target_stance != "neutral" and entry_stance == target_stance:
        score += 20

    candidate = f"{entry.occasion} {entry.saying}".lower()
    kw_hits = sum(keyword in candidate for keyword in _query_keywords(plain_text))
    score += min(24, 6 * kw_hits)
    # 与当前句无关的「已站稳」自生成金句不注入；弱相关则降权
    if kw_hits == 0 and entry.source == "llm_success":
        if entry.status == "active" or int(entry.support) >= 3:
            return None
        score -= 40
    return score


def retrieve_expressions_for_message(
    group_id: int,
    plain_text: str,
    *,
    limit: int,
    bot_id: int = 0,
    blocked_openers: Iterable[str] | None = None,
) -> list[ExpressionEntry]:
    """Return the highest-ranked non-rejected expressions for a group message."""
    target_bot_id = int(bot_id)
    blocked = {str(item).strip() for item in (blocked_openers or []) if str(item).strip()}
    scored: list[tuple[int, ExpressionEntry]] = []
    for entry in list_group_expressions(int(group_id), limit=100):
        if target_bot_id and entry.bot_id not in {0, target_bot_id}:
            continue
        score = score_expression_for_query(entry, plain_text)
        if score is None:
            continue
        opener = expression_opener_key(entry.saying)
        if opener and opener in blocked:
            score -= 80
        scored.append((score, entry))
    scored.sort(key=lambda item: (-item[0], -item[1].updated_at, item[1].entry_id))

    picked: list[ExpressionEntry] = []
    seen_openers: set[str] = set()
    for score, entry in scored:
        if score < 20:
            continue
        opener = expression_opener_key(entry.saying)
        if opener and opener in seen_openers:
            continue
        if opener:
            seen_openers.add(opener)
        picked.append(entry)
        if len(picked) >= max(1, int(limit)):
            return picked
    # 开头多样性凑不满时再回填，但仍避开 blocked
    for score, entry in scored:
        if entry in picked or score < 10:
            continue
        opener = expression_opener_key(entry.saying)
        if opener and opener in blocked:
            continue
        picked.append(entry)
        if len(picked) >= max(1, int(limit)):
            break
    return picked


def build_expression_reference_block(entries: Iterable[ExpressionEntry], *, limit: int = 5) -> str:
    lines: list[str] = []
    seen_openers: set[str] = set()
    for entry in entries:
        occasion = sanitize_prompt_literal(str(entry.occasion or "").strip(), max_len=20)
        saying = sanitize_prompt_literal(str(entry.saying or "").strip(), max_len=24)
        if not occasion or not saying:
            continue
        opener = expression_opener_key(saying)
        if opener and opener in seen_openers:
            continue
        if opener:
            seen_openers.add(opener)
        lines.append(f"{occasion}→{saying}")
        if len(lines) >= max(1, int(limit)):
            break
    return f"\n【表达参考】\n{chr(10).join(lines)}。" if lines else ""
