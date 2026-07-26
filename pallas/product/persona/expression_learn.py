"""Safely learn short group expressions from successful utterances."""

from __future__ import annotations

import re
import time

from pallas.product.llm.config import get_llm_config
from pallas.product.llm.corpus_contamination import is_llm_learning_safe, match_corpus_learn_block
from pallas.product.llm.repeater_feedback import is_systemish_promote_text
from pallas.product.persona.corpus_expression_habits import infer_expression_affect_stance
from pallas.product.persona.expression_bank import ExpressionEntry, append_or_merge_expression, build_entry_id
from pallas.product.persona.occasion import OccasionTag

_COMMANDISH_RE = re.compile(r"^(?:[/!！]|管理口令|封禁|解禁|禁言)", re.IGNORECASE)

# (group_id, saying) -> last learned unix ts；限制 llm_success 自强化回灌
_LLM_SUCCESS_LEARN_AT: dict[tuple[int, str], int] = {}


def clear_expression_learn_cooldown_state() -> None:
    _LLM_SUCCESS_LEARN_AT.clear()


def clean_expression_saying(text: str) -> str:
    return " ".join(str(text or "").split())[:20].rstrip()


def is_saying_safe_for_expression(text: str) -> bool:
    plain = " ".join(str(text or "").split())
    if not 2 <= len(plain) <= 20:
        return False
    if "[cq:" in plain.lower() or _COMMANDISH_RE.search(plain):
        return False
    if is_systemish_promote_text(plain):
        return False
    if not is_llm_learning_safe(plain):
        return False
    from pallas.product.persona.peer_bots_prompt import is_peer_harm_expression

    if is_peer_harm_expression(plain):
        return False
    return match_corpus_learn_block(plain) is None


def infer_expression_occasion(text: str, stance: str) -> str:
    plain = str(text or "").strip()
    if stance == "complain":
        if any(cue in plain for cue in ("加班", "上班", "下班")):
            return OccasionTag.VENTING
        if "抽卡" in plain:
            return OccasionTag.VENTING
        return OccasionTag.VENTING
    if stance == "warm":
        return OccasionTag.WARM_REPLY
    if stance == "echo":
        return OccasionTag.AGREEMENT
    if any(cue in plain for cue in ("早", "晚安", "晚")):
        return OccasionTag.GREETING
    return OccasionTag.SMALLTALK


def propose_expression_from_utterance(
    text: str,
    *,
    source: str,
    channel: str,
    scene_tier: str = "",
) -> ExpressionEntry | None:
    saying = clean_expression_saying(text)
    if not is_saying_safe_for_expression(saying):
        return None
    stance = infer_expression_affect_stance(saying)
    occasion = infer_expression_occasion(saying, stance)
    now = int(time.time())
    key = (occasion, saying)
    return ExpressionEntry(
        entry_id=build_entry_id(0, key),
        group_id=0,
        occasion=occasion,
        saying=saying,
        source=source,  # type: ignore[arg-type]
        channel=str(channel or "").strip(),
        scene_tier=str(scene_tier or "").strip(),
        status="shadow",
        affect_hint=stance,
        created_at=now,
        updated_at=now,
    )


def note_expression_from_utterance(group_id: int, text: str, **meta: object) -> ExpressionEntry | None:
    cfg = get_llm_config()
    if not cfg.llm_expression_learn_enabled:
        return None
    source = str(meta.get("source") or "llm_success")
    target_group_id = int(group_id)
    bot_id = int(meta.get("bot_id") or 0)
    # 口癖：从完整成功回复抽短习惯，不依赖表达库截断句
    if source == "llm_success" and bot_id > 0 and target_group_id > 0:
        try:
            from pallas.product.persona.catchphrase_bank import (
                propose_catchphrases_from_utterance,
                schedule_llm_catchphrase_mine,
            )

            propose_catchphrases_from_utterance(bot_id, target_group_id, text)
            schedule_llm_catchphrase_mine(bot_id, target_group_id, text)
        except Exception:
            pass
    draft = propose_expression_from_utterance(
        text,
        source=source,
        channel=str(meta.get("channel") or "group"),
        scene_tier=str(meta.get("scene_tier") or ""),
    )
    if draft is None:
        return None
    if target_group_id <= 0:
        return None
    saying = draft.saying
    support = 1
    if source == "llm_success":
        cooldown = max(0, int(getattr(cfg, "llm_expression_learn_cooldown_sec", 300) or 0))
        now = int(time.time())
        key = (target_group_id, saying)
        last = _LLM_SUCCESS_LEARN_AT.get(key)
        if cooldown > 0 and last is not None and now - last < cooldown:
            return None
        _LLM_SUCCESS_LEARN_AT[key] = now
    entry = draft.model_copy(
        update={
            "entry_id": build_entry_id(target_group_id, (draft.occasion, draft.saying)),
            "group_id": target_group_id,
            "support": support,
            "bot_id": bot_id,
        }
    )
    saved = append_or_merge_expression(entry)
    if saved.source == "llm_success":
        try:
            from pallas.product.persona.expression_promote import maybe_auto_promote_for_group

            maybe_auto_promote_for_group(target_group_id)
        except Exception:
            pass
    return saved


def learn_expressions_from_group_messages(
    group_id: int,
    texts: list[str],
    *,
    bot_id: int = 0,
    max_notes: int = 5,
) -> list[ExpressionEntry]:
    if not get_llm_config().llm_expression_learn_enabled or int(group_id) <= 0:
        return []
    saved: list[ExpressionEntry] = []
    for text in texts:
        if len(saved) >= max(0, int(max_notes)):
            break
        entry = note_expression_from_utterance(
            group_id,
            text,
            source="group_observe",
            channel="group_observe",
            bot_id=bot_id,
        )
        if entry is not None:
            saved.append(entry)
    return saved
