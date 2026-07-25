"""Retrieve group expressions suitable for the current message."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

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


def score_expression_for_query(entry: ExpressionEntry, plain_text: str) -> int | None:
    """Return a relevance score, or None for entries that cannot be injected."""
    if entry.status == "rejected":
        return None

    score = 100 if entry.status == "active" else 50
    score += min(max(1, int(entry.support)), 10)
    if entry.source == "llm_success":
        score += 5

    target_stance = infer_expression_affect_stance(plain_text)
    entry_stance = str(entry.affect_hint or "").strip() or infer_expression_affect_stance(entry.saying)
    if target_stance != "neutral" and entry_stance == target_stance:
        score += 20

    candidate = f"{entry.occasion} {entry.saying}".lower()
    score += min(24, 6 * sum(keyword in candidate for keyword in _query_keywords(plain_text)))
    return score


def retrieve_expressions_for_message(
    group_id: int,
    plain_text: str,
    *,
    limit: int,
    bot_id: int = 0,
) -> list[ExpressionEntry]:
    """Return the highest-ranked non-rejected expressions for a group message."""
    target_bot_id = int(bot_id)
    scored: list[tuple[int, ExpressionEntry]] = []
    for entry in list_group_expressions(int(group_id), limit=100):
        if target_bot_id and entry.bot_id not in {0, target_bot_id}:
            continue
        score = score_expression_for_query(entry, plain_text)
        if score is not None:
            scored.append((score, entry))
    scored.sort(key=lambda item: (-item[0], -item[1].updated_at, item[1].entry_id))
    return [entry for _score, entry in scored[: max(1, int(limit))]]


def build_expression_reference_block(entries: Iterable[ExpressionEntry], *, limit: int = 5) -> str:
    lines: list[str] = []
    for entry in entries:
        occasion = sanitize_prompt_literal(str(entry.occasion or "").strip(), max_len=20)
        saying = sanitize_prompt_literal(str(entry.saying or "").strip(), max_len=24)
        if not occasion or not saying:
            continue
        lines.append(f"{occasion}→{saying}")
        if len(lines) >= max(1, int(limit)):
            break
    return f"\n【表达参考】\n{chr(10).join(lines)}。" if lines else ""
