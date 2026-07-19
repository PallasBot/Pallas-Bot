"""将维护者反馈样本注入 llm_chat system prompt。"""

from __future__ import annotations

import re

from pallas.product.llm.kernel.memory_governance import can_read_behavioral_learning
from pallas.product.llm.repeater_feedback import list_group_feedback_entries
from pallas.product.persona.prompt_guard import sanitize_prompt_literal

_AVOID_REPLY_LIMIT = 3
_GOOD_REPLY_LIMIT = 2
_CORRECTION_LIMIT = 2
_CORRECTION_MATCH_LIMIT = 2
_MAX_REPLY_SNIPPET = 28
_MAX_USER_SNIPPET = 24
_MAX_CORRECTION_REPLY = 48
_KAOMOJI_SUFFIX_RE = re.compile(r"\(\*[^)]{1,16}\*\)\s*$")


def summarize_reply_snippet(text: str, *, max_len: int = _MAX_REPLY_SNIPPET) -> str:
    plain = str(text or "").strip()
    if not plain:
        return ""
    compact = _KAOMOJI_SUFFIX_RE.sub("", plain).strip("，,。！!？?~～ ")
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 1].rstrip("，,。！!？?~～ ") + "…"


def summarize_user_trigger(text: str, *, max_len: int = _MAX_USER_SNIPPET) -> str:
    plain = str(text or "").strip()
    if not plain:
        return ""
    if len(plain) <= max_len:
        return plain
    return plain[: max_len - 1].rstrip("，,。！!？?~～ ") + "…"


def correction_matches_query(user_text: str, query_text: str) -> bool:
    user = str(user_text or "").strip()
    query = str(query_text or "").strip()
    if not user or not query:
        return False
    if len(user) >= 3 and user in query:
        return True
    if len(query) >= 3 and query in user:
        return True
    shorter, longer = (user, query) if len(user) <= len(query) else (query, user)
    for size in range(min(len(shorter), 12), 3, -1):
        for start in range(len(shorter) - size + 1):
            chunk = shorter[start : start + size]
            if chunk in longer:
                return True
    return False


def build_group_feedback_chat_hint(*, group_id: int, user_text: str = "", limit: int = 40) -> str:
    if not can_read_behavioral_learning() or int(group_id) <= 0:
        return ""
    rows = list_group_feedback_entries(group_id=int(group_id), limit=max(1, int(limit)))
    if not rows:
        return ""

    query = str(user_text or "").strip()
    corrected_rows = [item for item in rows if str(item.corrected_reply_text or "").strip()]
    matched_corrections: list[str] = []
    general_corrections: list[str] = []
    seen_correction: set[str] = set()
    for item in reversed(corrected_rows):
        corr_snip = summarize_reply_snippet(item.corrected_reply_text, max_len=_MAX_CORRECTION_REPLY)
        if not corr_snip or corr_snip in seen_correction:
            continue
        user_snip = summarize_user_trigger(item.user_text)
        if not user_snip:
            continue
        line = f"用户说「{user_snip}」时维护者期望类似这样接：{corr_snip}"
        if query and correction_matches_query(item.user_text, query):
            matched_corrections.append(line)
        else:
            general_corrections.append(line)
        seen_correction.add(corr_snip)

    hints: list[str] = list(matched_corrections[:_CORRECTION_MATCH_LIMIT])
    remaining = max(0, _CORRECTION_LIMIT - len(hints))
    hints.extend(general_corrections[:remaining])

    good_rows = [item for item in rows if item.eligible_for_bias and str(item.reply_text or "").strip()]
    bad_rows = [item for item in rows if not item.eligible_for_bias and str(item.reply_text or "").strip()]

    good_snippets: list[str] = []
    seen_good: set[str] = set()
    for item in reversed(good_rows):
        snippet = summarize_reply_snippet(item.reply_text)
        if not snippet or snippet in seen_good:
            continue
        seen_good.add(snippet)
        good_snippets.append(snippet)
        if len(good_snippets) >= _GOOD_REPLY_LIMIT:
            break
    good_snippets.reverse()
    if good_snippets:
        hints.append("本群近期较好的接话可参考：" + "；".join(good_snippets))

    avoid_snippets: list[str] = []
    seen_bad: set[str] = set()
    for item in reversed(bad_rows):
        snippet = summarize_reply_snippet(item.reply_text)
        if not snippet or snippet in seen_bad:
            continue
        seen_bad.add(snippet)
        avoid_snippets.append(snippet)
        if len(avoid_snippets) >= _AVOID_REPLY_LIMIT:
            break
    avoid_snippets.reverse()
    if avoid_snippets:
        hints.append("以下写法已被维护者排除，不要模仿：" + "；".join(avoid_snippets))

    kaomoji_bad = sum(1 for item in bad_rows if _KAOMOJI_SUFFIX_RE.search(str(item.reply_text or "")))
    if kaomoji_bad >= 2 and not any("颜文字" in line for line in hints):
        hints.append("本群维护者多次排除句尾 ASCII 颜文字（如 (*^_^*)），这轮别加。")

    if not hints:
        return ""
    body = sanitize_prompt_literal("\n- ".join(hints), max_len=560)
    return f"\n【维护者样本参考】\n- {body}"


async def load_repeater_feedback_system_suffix(*, group_id: int, user_text: str = "") -> str:
    import asyncio

    hint = await asyncio.to_thread(
        build_group_feedback_chat_hint,
        group_id=int(group_id),
        user_text=str(user_text or ""),
    )
    return str(hint or "").strip()
