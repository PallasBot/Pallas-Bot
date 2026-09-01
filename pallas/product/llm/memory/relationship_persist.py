"""关系备注静默沉淀入口（教导除外）。"""

from __future__ import annotations

import asyncio

from nonebot import logger

from pallas.product.llm.config import LlmConfig, get_llm_config
from pallas.product.llm.memory.affinity_scorer import score_affinity_with_llm
from pallas.product.llm.memory.rate_limit import DailyBudget, WriteCooldown
from pallas.product.llm.memory.relationship import relationship_auto_fact_is_admissible
from pallas.product.llm.memory.relationship_auto import (
    extract_relationship_affinity_delta,
    extract_relationship_attitude_delta,
    parse_relationship_observe,
)
from pallas.product.llm.memory.relationship_store import upsert_relationship_profile

_HARD_SPEAK_TRIGGERS = frozenset({"to_me", "mention", "followup"})
_AMBIENT_TRIGGERS = frozenset({"ambient"})
_affinity_llm_last_scored = WriteCooldown()
_affinity_llm_daily_budget = DailyBudget()


def _affinity_llm_daily_budget_ok(*, cfg: LlmConfig) -> bool:
    return _affinity_llm_daily_budget.ok(int(getattr(cfg, "llm_relationship_affinity_llm_daily_limit", 0) or 0))


def _bump_affinity_llm_daily_budget(*, cfg: LlmConfig) -> None:
    _affinity_llm_daily_budget.bump(int(getattr(cfg, "llm_relationship_affinity_llm_daily_limit", 0) or 0))


async def maybe_persist_relationship_from_utterance(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    plain_text: str,
    *,
    speak_trigger: str = "",
    cfg: LlmConfig | None = None,
) -> bool:
    """硬触发路径静默写关系事实/态度；ambient 仅在开启时做规则好感度观察，不建事实、不跑 LLM。"""
    if not user_id:
        return False
    c = cfg or get_llm_config()
    if not c.llm_relationship_notes_enabled:
        return False
    trigger = str(speak_trigger or "").strip()
    is_hard = trigger in _HARD_SPEAK_TRIGGERS
    is_ambient = trigger in _AMBIENT_TRIGGERS
    if not is_hard and not (is_ambient and c.llm_relationship_affinity_ambient_enabled):
        return False

    fact: str | None = None
    source = "auto"
    if is_hard:
        if c.llm_relationship_observe_enabled:
            fact = parse_relationship_observe(plain_text)
            if fact:
                source = "observe"

    warmth_add = 0.0
    assertiveness_add = 0.0
    if is_hard and c.llm_relationship_auto_persist_enabled:
        warmth_add, assertiveness_add = extract_relationship_attitude_delta(plain_text)

    affinity_add = 0.0
    affinity_source = "rules"
    use_llm = False
    if c.llm_relationship_affinity_enabled and (is_hard or is_ambient):
        affinity_add = extract_relationship_affinity_delta(plain_text)
        if affinity_add == 0.0 and is_hard:
            use_llm = True

    if use_llm:
        key = (int(bot_id), int(group_id or 0), int(user_id))
        cooldown = max(0, int(getattr(c, "llm_relationship_affinity_llm_cooldown_s", 24) or 24))
        if _affinity_llm_last_scored.ok(key, cooldown):
            _affinity_llm_last_scored.mark(key)
            if _affinity_llm_daily_budget_ok(cfg=c):
                scored = await score_affinity_with_llm(plain_text, cfg=c)
                if scored is not None and scored.get("affinity_delta") is not None:
                    affinity_add = float(scored["affinity_delta"])
                    affinity_source = "llm"
                    _bump_affinity_llm_daily_budget(cfg=c)
                    # 事实准入独立于好感度；中性消息也可能包含直接事实。
                    note = str(scored.get("stable_note") or "").strip()
                    if (
                        note
                        and float(scored.get("confidence") or 0.0) >= 0.5
                        and relationship_auto_fact_is_admissible(note)
                    ):
                        fact = note
                        source = "observe"

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


def schedule_persist_relationship_from_utterance(
    bot_id: int,
    group_id: int | None,
    user_id: int,
    plain_text: str,
    *,
    speak_trigger: str = "",
    cfg: LlmConfig | None = None,
) -> None:
    """后台化静默沉淀，避免好感度 LLM 兜底定分阻塞主回复链路。"""
    c = cfg or get_llm_config()
    if not user_id or not c.llm_relationship_notes_enabled:
        return
    try:
        asyncio.get_running_loop().create_task(
            maybe_persist_relationship_from_utterance(
                int(bot_id),
                group_id,
                int(user_id),
                plain_text,
                speak_trigger=speak_trigger,
                cfg=c,
            ),
            name=f"relationship_persist:{int(bot_id)}:{int(group_id or 0)}:{int(user_id)}",
        )
    except RuntimeError:
        return


def clear_affinity_state_for_tests() -> None:
    _affinity_llm_last_scored.clear()
    _affinity_llm_daily_budget.reset()
