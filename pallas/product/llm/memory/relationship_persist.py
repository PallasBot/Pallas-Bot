"""关系备注静默沉淀入口（教导除外）。"""

from __future__ import annotations

import time

from nonebot import logger

from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.llm.memory.affinity_scorer import score_affinity_with_llm
from pallas.product.llm.memory.relationship_auto import (
    extract_relationship_affinity_delta,
    extract_relationship_attitude_delta,
    parse_relationship_observe,
)
from pallas.product.llm.memory.relationship_store import upsert_relationship_profile

_HARD_SPEAK_TRIGGERS = frozenset({"to_me", "mention", "followup"})
_LLM_AFFINITY_COOLDOWN_SEC = 60
_llm_affinity_last_scored: dict[tuple[int, int, int], float] = {}


async def maybe_persist_relationship_from_utterance(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    plain_text: str,
    *,
    speak_trigger: str = "",
    cfg: LlmConfig | None = None,
) -> bool:
    """硬触发路径静默写关系事实/态度；ambient 不写。"""
    if not user_id:
        return False
    c = cfg or get_llm_config()
    if not c.llm_relationship_notes_enabled:
        return False
    trigger = str(speak_trigger or "").strip()
    if trigger not in _HARD_SPEAK_TRIGGERS:
        return False

    fact: str | None = None
    source = "auto"
    if c.llm_relationship_observe_enabled:
        fact = parse_relationship_observe(plain_text)
        if fact:
            source = "observe"

    warmth_add = 0.0
    assertiveness_add = 0.0
    if c.llm_relationship_auto_persist_enabled:
        warmth_add, assertiveness_add = extract_relationship_attitude_delta(plain_text)

    affinity_add = 0.0
    affinity_source = "rules"
    if c.llm_relationship_affinity_enabled:
        affinity_add = extract_relationship_affinity_delta(plain_text)
        if affinity_add == 0.0:
            key = (int(bot_id), int(group_id or 0), int(user_id))
            last = _llm_affinity_last_scored.get(key, 0.0)
            now = time.time()
            cooldown = max(0, int(getattr(c, "llm_relationship_affinity_llm_cooldown_s", 60) or 60))
            if now - last >= cooldown:
                _llm_affinity_last_scored[key] = now
                scored = await score_affinity_with_llm(plain_text, cfg=c)
                if scored is not None and scored.get("affinity_delta"):
                    affinity_add = float(scored["affinity_delta"])
                    affinity_source = "llm"

    if not fact and warmth_add == 0.0 and assertiveness_add == 0.0 and affinity_add == 0.0:
        return False
    try:
        ok = await upsert_relationship_profile(
            bot_id,
            group_id,
            user_id,
            content=fact,
            source=source,
            warmth_delta_add=warmth_add,
            assertiveness_delta_add=assertiveness_add,
            affinity_delta_add=affinity_add,
            merge_content=True,
            cfg=c,
        )
    except Exception:
        logger.debug("relationship silent persist skipped")
        return False
    if ok:
        fact_preview = (fact or "")[:48]
        logger.info(
            "Relationship persistence succeeded for source [{}], trigger [{}], bot [{}], group [{}], user [{}], "
            "fact [{!r}], warmth add [{}], assertiveness add [{}], affinity add [{}] (source [{}])",
            source,
            trigger,
            bot_id,
            group_id,
            user_id,
            fact_preview,
            warmth_add,
            assertiveness_add,
            affinity_add,
            affinity_source,
        )
    return ok
