"""Safely learn short group expressions from successful utterances."""

from __future__ import annotations

import re
import time

from pallas.product.llm.config import get_llm_config
from pallas.product.llm.corpus_contamination import is_llm_learning_safe, match_corpus_learn_block
from pallas.product.llm.repeater_feedback import is_systemish_promote_text
from pallas.product.persona.corpus_expression_habits import infer_expression_affect_stance
from pallas.product.persona.expression_bank import ExpressionEntry, append_or_merge_expression, build_entry_id

_COMMANDISH_RE = re.compile(r"^(?:[/!！]|管理口令|封禁|解禁|禁言)", re.IGNORECASE)


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
    return match_corpus_learn_block(plain) is None


def infer_expression_occasion(text: str, stance: str) -> str:
    plain = str(text or "").strip()
    if stance == "complain":
        if any(cue in plain for cue in ("加班", "上班", "下班")):
            return "吐槽加班"
        if "抽卡" in plain:
            return "吐槽抽卡"
        return "吐槽"
    if stance == "warm":
        return "感谢回应" if any(cue in plain for cue in ("谢", "辛苦", "好耶")) else "友好回应"
    if stance == "echo":
        return "附和"
    if any(cue in plain for cue in ("早", "晚安", "晚")):
        return "日常问候"
    return "日常接话"


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
    if not get_llm_config().llm_expression_learn_enabled:
        return None
    source = str(meta.get("source") or "llm_success")
    draft = propose_expression_from_utterance(
        text,
        source=source,
        channel=str(meta.get("channel") or "group"),
        scene_tier=str(meta.get("scene_tier") or ""),
    )
    if draft is None:
        return None
    target_group_id = int(group_id)
    if target_group_id <= 0:
        return None
    entry = draft.model_copy(
        update={
            "entry_id": build_entry_id(target_group_id, (draft.occasion, draft.saying)),
            "group_id": target_group_id,
            "support": 2,
            "bot_id": int(meta.get("bot_id") or 0),
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
