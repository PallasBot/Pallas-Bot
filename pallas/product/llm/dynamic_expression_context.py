"""动态表达参考：群近场语料 + affect trigger（@ 闲聊与 repeater 共用）。"""

from __future__ import annotations

import time

from pallas.core.foundation.db import make_message_repository
from pallas.product.llm.near_field_scorer import (
    ANSWER_SOURCE,
    RECENT_LIVE_SOURCE,
    select_scored_expression_candidates,
)
from pallas.product.persona.affect_triggers import extract_affect_triggers
from pallas.product.persona.corpus_expression_habits import infer_expression_affect_stance
from pallas.product.persona.dynamic_expression import (
    build_affect_trigger_turn_hint,
    format_dynamic_expression_hint,
    format_situational_expression_pairs,
    match_message_affect_triggers,
)


def extract_chat_trigger_keywords(text: str) -> list[str]:
    plain = str(text or "").strip()
    if not plain:
        return []
    try:
        from packages.repeater.model import ChatData
    except Exception:
        return []

    try:
        data = ChatData(
            group_id=0,
            user_id=0,
            raw_message=plain,
            plain_text=plain,
            time=0,
            bot_id=0,
        )
    except Exception:
        return []
    return [item for item in getattr(data, "_keywords_list", []) if item]


async def load_recent_live_expression_rows(
    group_id: int,
    text: str,
    *,
    bot_id: int | None = None,
    current_user_id: int | None = None,
) -> list[dict[str, object]]:
    from collections import Counter

    trigger_keywords = extract_chat_trigger_keywords(text)
    repo = make_message_repository()
    try:
        messages = await repo.find_recent_in_group(int(group_id), before_time=int(time.time()) + 1, limit=32)
    except Exception:
        return []

    user_weights = Counter(int(getattr(msg, "user_id", 0) or 0) for msg in messages)
    user_topic_hits = Counter()
    for msg in messages:
        plain = str(getattr(msg, "plain_text", "") or "").strip()
        if not plain or "[CQ:" in plain:
            continue
        keywords = str(getattr(msg, "keywords", "") or "").strip()
        if trigger_keywords and keywords and not any(keyword in keywords for keyword in trigger_keywords):
            continue
        user_id = int(getattr(msg, "user_id", 0) or 0)
        user_topic_hits[user_id] += 1

    rows: list[dict[str, object]] = []
    for msg in messages:
        plain = str(getattr(msg, "plain_text", "") or "").strip()
        if not plain or "[CQ:" in plain:
            continue
        user_id = int(getattr(msg, "user_id", 0) or 0)
        if current_user_id is not None and user_id == int(current_user_id):
            continue
        bot_msg_id = int(getattr(msg, "bot_id", 0) or 0)
        if bot_id is not None and user_id == int(bot_id):
            continue
        if bot_id is not None and bot_msg_id != 0 and bot_msg_id != int(bot_id):
            continue
        if trigger_keywords:
            keywords = str(getattr(msg, "keywords", "") or "").strip()
            if keywords and not any(keyword in keywords for keyword in trigger_keywords):
                continue
        rows.append({
            "text": plain,
            "count": int(user_weights.get(user_id, 0) or 0),
            "topic_hits": int(user_topic_hits.get(user_id, 0) or 0),
            "keywords": str(getattr(msg, "keywords", "") or "").strip(),
            "time": int(getattr(msg, "time", 0) or 0),
            "user_id": user_id,
            "source": RECENT_LIVE_SOURCE,
        })
    rows.sort(
        key=lambda item: (
            -int(item.get("topic_hits") or 0),
            -int(item.get("count") or 0),
            -int(item.get("time") or 0),
        )
    )
    return rows


async def build_dynamic_expression_hint(
    group_id: int | None,
    text: str,
    *,
    bot_id: int | None = None,
    current_user_id: int | None = None,
) -> str:
    if group_id is None:
        return ""
    plain = str(text or "").strip()
    if not plain:
        return ""

    from pallas.core.foundation.db import make_group_config_repository

    try:
        group_config = await make_group_config_repository().get(int(group_id))
    except Exception:
        group_config = None
    profile = getattr(group_config, "style_profile", None) if group_config is not None else None
    triggers = extract_affect_triggers(profile if isinstance(profile, dict) else None)
    matched = match_message_affect_triggers(plain, triggers)
    trigger_hint = build_affect_trigger_turn_hint(plain, matched)

    recent_rows = await load_recent_live_expression_rows(
        int(group_id),
        plain,
        bot_id=bot_id,
        current_user_id=current_user_id,
    )
    answer_rows: list[dict[str, object]] = []
    try:
        from pallas.core.foundation.db.context_repo_access import get_shared_context_repository
    except Exception:
        repo = None
    else:
        repo = get_shared_context_repository()
    list_answers = getattr(repo, "list_answers_for_group_since", None) if repo is not None else None
    if callable(list_answers):
        try:
            answers = await list_answers(int(group_id), 0)
        except Exception:
            answers = []
        else:
            for ans in answers:
                messages = getattr(ans, "messages", None) or []
                sample = str(messages[0] if messages else getattr(ans, "keywords", "") or "").strip()
                answer_rows.append({
                    "text": sample,
                    "count": int(getattr(ans, "count", 0) or 0),
                    "keywords": str(getattr(ans, "keywords", "") or "").strip(),
                    "source": ANSWER_SOURCE,
                    "time": int(getattr(ans, "time", 0) or 0),
                    "topic_hits": 0,
                })

    trigger_keywords = extract_chat_trigger_keywords(plain)
    target_stance = infer_expression_affect_stance(plain)
    merged_rows = list(recent_rows) + answer_rows
    candidates = select_scored_expression_candidates(
        merged_rows,
        target_stance=target_stance,
        trigger_keywords=trigger_keywords,
        query_text=plain,
        limit=3,
        reference_min_len=2,
        reference_min_cjk=2,
    )
    situational_lines = format_situational_expression_pairs(matched, candidates, user_text=plain)
    return format_dynamic_expression_hint(trigger_hint, situational_lines)
