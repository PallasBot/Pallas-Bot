"""群消息语气扫描：基表 + 标点启发式，供 group_profiler 与 LLM 摘要。"""

from __future__ import annotations

from typing import Any

from .affect_lexicon import LEXICON_VERSION, baseline_polite_examples, load_affect_lexicon, punct_aggression_score


def scan_plain_tone(
    text: str,
    *,
    polite_patterns: tuple[str, ...],
    harsh_patterns: tuple[str, ...],
) -> dict[str, bool | float]:
    plain = str(text or "").strip()
    lower = plain.lower()
    harsh_hit = any(token in lower for token in harsh_patterns) if plain else False
    polite_hit = any(token in lower for token in polite_patterns) if plain else False
    return {
        "harsh_hit": harsh_hit,
        "polite_hit": polite_hit,
        "punct_aggression": punct_aggression_score(plain),
    }


def summarize_group_message_tones(plain_texts: list[str]) -> dict[str, Any]:
    lex = load_affect_lexicon()
    polite_patterns = lex["polite"]
    harsh_patterns = lex["harsh"]

    total = 0
    harsh_msgs = 0
    polite_msgs = 0
    punct_sum = 0.0

    for text in plain_texts:
        plain = str(text or "").strip()
        if not plain:
            continue
        total += 1
        flags = scan_plain_tone(plain, polite_patterns=polite_patterns, harsh_patterns=harsh_patterns)
        if flags["harsh_hit"]:
            harsh_msgs += 1
        if flags["polite_hit"]:
            polite_msgs += 1
        punct_sum += float(flags["punct_aggression"])

    if total <= 0:
        return {
            "lexicon_version": LEXICON_VERSION,
            "message_count": 0,
            "harsh_msg_ratio": 0.0,
            "polite_msg_ratio": 0.0,
            "punct_aggression_avg": 0.0,
            "civility_score": 0.0,
            "polite_lexicon_samples": baseline_polite_examples(6),
        }

    harsh_ratio = harsh_msgs / total
    polite_ratio = polite_msgs / total
    punct_avg = punct_sum / total
    civility = max(-1.0, min(1.0, polite_ratio * 0.65 - harsh_ratio * 0.85 - punct_avg * 0.35))

    return {
        "lexicon_version": LEXICON_VERSION,
        "message_count": total,
        "harsh_msg_ratio": round(harsh_ratio, 4),
        "polite_msg_ratio": round(polite_ratio, 4),
        "punct_aggression_avg": round(punct_avg, 4),
        "civility_score": round(civility, 4),
        "polite_lexicon_samples": baseline_polite_examples(6),
    }
