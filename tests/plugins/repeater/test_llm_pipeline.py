from __future__ import annotations

from packages.repeater.responder import Responder
from pallas.product.persona.model import ResolvedPersona


def test_evaluate_llm_candidate_text_rejects_empty_text() -> None:
    accepted, score = Responder.evaluate_llm_candidate_text("", base_score=1.0, min_score=0.5)
    assert accepted is False
    assert score == 0.0


def test_evaluate_llm_candidate_text_accepts_grounded_text_above_threshold() -> None:
    accepted, score = Responder.evaluate_llm_candidate_text("这句挺像群里会说的话", base_score=0.9, min_score=0.5)
    assert accepted is True
    assert score == 0.9


def test_evaluate_llm_candidate_text_penalizes_duplicate_recent_reply() -> None:
    accepted, score = Responder.evaluate_llm_candidate_text(
        "这句挺像群里会说的话",
        base_score=0.9,
        min_score=0.5,
        recent_sent=["这句挺像群里会说的话"],
    )
    assert accepted is False
    assert score < 0.5


def test_evaluate_llm_candidate_text_prefers_short_text_for_short_persona() -> None:
    from pallas.product.persona.group_expression_profile import GroupExpressionProfile, GroupReplyShapeHint

    persona = ResolvedPersona(
        group_expression_profile=GroupExpressionProfile(reply_shape=GroupReplyShapeHint(length_pref="short"))
    )
    accepted_short, score_short = Responder.evaluate_llm_candidate_text(
        "好耶",
        base_score=0.5,
        min_score=0.5,
        persona=persona,
    )
    accepted_long, score_long = Responder.evaluate_llm_candidate_text(
        "这句话明显更长一些而且不像短促接话",
        base_score=0.5,
        min_score=0.5,
        persona=persona,
    )
    assert accepted_short is True
    assert accepted_long is False
    assert score_short > score_long


def test_evaluate_llm_candidate_text_applies_affect_trigger_bonus() -> None:
    persona = ResolvedPersona()
    accepted, score = Responder.evaluate_llm_candidate_text(
        "这下稳了",
        base_score=0.4,
        min_score=0.5,
        persona=persona,
        affect_triggers=[{"phrase": "稳", "weight": 1.0}],
    )
    assert accepted is True
    assert score >= 0.5


def test_evaluate_llm_candidate_text_ghost_prefers_short_expressive_text() -> None:
    persona = ResolvedPersona()
    accepted_short, score_short = Responder.evaluate_llm_candidate_text(
        "啊？",
        base_score=0.45,
        min_score=0.5,
        persona=persona,
        reply_mode="ghost",
    )
    accepted_long, score_long = Responder.evaluate_llm_candidate_text(
        "这句话长很多而且没有那么跳脱",
        base_score=0.45,
        min_score=0.5,
        persona=persona,
        reply_mode="ghost",
    )
    assert accepted_short is True
    assert score_short > score_long
