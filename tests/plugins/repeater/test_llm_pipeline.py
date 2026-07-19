from __future__ import annotations

import pytest

from packages.repeater.llm_pipeline import (
    RepeaterLlmPlan,
    build_repeater_llm_plan,
    build_stitch_candidate,
    run_repeater_llm_plan,
)
from packages.repeater.responder import ReplyBundle, Responder
from pallas.product.persona.model import ResolvedPersona


def test_build_repeater_llm_plan_orders_grounded_stages_before_fallback() -> None:
    bundle = ReplyBundle(
        answer_list=["候选一", "候选二"],
        answer_keywords="测试",
        message_pool=["候选一", "候选二", "候选三"],
    )
    plan = build_repeater_llm_plan(
        bundle,
        llm_enabled=True,
        select_enabled=True,
        polish_enabled=True,
        polish_lite_enabled=False,
    )
    assert plan.stage_names == ["select", "rewrite", "stitch", "generate"]
    assert plan.fallback_text == "候选一"


def test_build_repeater_llm_plan_uses_generate_only_when_no_grounded_candidate() -> None:
    bundle = ReplyBundle(
        answer_list=[],
        answer_keywords="测试",
        message_pool=[],
    )
    plan = build_repeater_llm_plan(
        bundle,
        llm_enabled=True,
        select_enabled=True,
        polish_enabled=True,
        polish_lite_enabled=False,
    )
    assert plan.stage_names == ["generate"]
    assert plan.fallback_text == ""


def test_evaluate_llm_candidate_text_rejects_empty_text() -> None:
    accepted, score = Responder.evaluate_llm_candidate_text("", base_score=1.0, min_score=0.5)
    assert accepted is False
    assert score == 0.0


def test_evaluate_llm_candidate_text_accepts_grounded_text_above_threshold() -> None:
    accepted, score = Responder.evaluate_llm_candidate_text("这句挺像群里会说的话", base_score=0.9, min_score=0.5)
    assert accepted is True
    assert score == 0.9


def test_build_stitch_candidate_joins_two_unique_short_candidates() -> None:
    stitched = build_stitch_candidate(["好耶", "这下稳了", "好耶"])
    assert stitched == "好耶，这下稳了"


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
    persona = ResolvedPersona(length_pref="short")
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


@pytest.mark.asyncio
async def test_run_repeater_llm_plan_stops_after_first_success() -> None:
    calls: list[str] = []

    async def stage_runner(name: str) -> bool:
        calls.append(name)
        return name == "rewrite"

    ok = await run_repeater_llm_plan(
        RepeaterLlmPlan(
            stage_names=["select", "rewrite", "stitch", "generate"],
            fallback_text="候选一",
            candidate_text="候选一",
            candidate_pool=["候选一", "候选二"],
        ),
        stage_runner=stage_runner,
    )
    assert ok is True
    assert calls == ["select", "rewrite"]


@pytest.mark.asyncio
async def test_pipeline_generate_runs_only_after_grounded_stages_fail() -> None:
    calls: list[str] = []

    async def stage_runner(name: str) -> bool:
        calls.append(name)
        return False

    ok = await run_repeater_llm_plan(
        RepeaterLlmPlan(
            stage_names=["select", "rewrite", "stitch", "generate"],
            fallback_text="候选一",
            candidate_text="候选一",
            candidate_pool=["候选一", "候选二"],
        ),
        stage_runner=stage_runner,
    )
    assert ok is False
    assert calls == ["select", "rewrite", "stitch", "generate"]
