"""兼容解析升级前已经提交的 Repeater LLM 选句任务。"""

from __future__ import annotations

import re

_SELECT_INDEX_RE = re.compile(r"(\d+)")


def filter_select_candidate_pool(candidates: list[str]) -> tuple[list[str], dict[str, int]]:
    from pallas.product.llm.corpus_contamination import is_corpus_learn_safe, is_llm_learning_safe

    raw_count = len(candidates)
    skipped_contamination = 0
    safe: list[str] = []
    seen: set[str] = set()
    for text in candidates:
        sample = str(text or "").strip()
        if not sample or "[CQ:" in sample:
            continue
        if not is_llm_learning_safe(sample) or not is_corpus_learn_safe(sample):
            skipped_contamination += 1
            continue
        if sample in seen:
            continue
        seen.add(sample)
        safe.append(sample)
    return safe, {
        "raw_count": raw_count,
        "safe_count": len(safe),
        "skipped_contamination": skipped_contamination,
    }


def build_select_user_text(
    user_text: str,
    candidates: list[str],
    *,
    context_hints: str = "",
) -> str:
    message = str(user_text or "").strip()
    pool = [str(item).strip() for item in candidates if str(item).strip()]
    if not message or not pool:
        return ""
    lines = [
        f"【用户消息】{message}",
    ]
    hints = str(context_hints or "").strip()
    if hints:
        lines.append(f"【语境参考】{hints}")
    lines.append("【候选回复】")
    lines.extend(f"{index}. {text}" for index, text in enumerate(pool, start=1))
    lines.append("请根据当前语境与情绪选出最合适的一条编号；都不合适则输出 0。")
    return "\n".join(lines)


def parse_select_response(raw: str, candidates: list[str]) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text == "0":
        return None
    pool = [str(item).strip() for item in candidates if str(item).strip()]
    if not pool:
        return None
    match = _SELECT_INDEX_RE.search(text)
    if match:
        index = int(match.group(1)) - 1
        if 0 <= index < len(pool):
            return pool[index]
    for sample in pool:
        if sample == text or text in sample:
            return sample
    return None


def resolve_select_callback_text(raw: str, candidates: list[str], fallback_text: str) -> str:
    selected = parse_select_response(raw, candidates)
    if selected:
        return selected
    fallback = str(fallback_text or "").strip()
    from pallas.product.llm.corpus_contamination import is_llm_learning_safe

    return fallback if is_llm_learning_safe(fallback) else ""
