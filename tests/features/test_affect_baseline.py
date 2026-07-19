from __future__ import annotations

import pytest

from pallas.product.persona.affect_baseline import (
    apply_affect_derived,
    derive_group_affect_bias,
    merge_affect_refine_into_profile,
)
from pallas.product.persona.auto import derive_persona_from_bot_id
from pallas.product.persona.model import ResolvedPersona
from pallas.product.persona.scorer import answer_popularity_multiplier, scaled_answer_threshold


def test_derive_persona_affect_differs_by_bot_id() -> None:
    a = derive_persona_from_bot_id(10001)
    b = derive_persona_from_bot_id(10002)
    assert a.warmth != b.warmth or a.assertiveness != b.assertiveness


def test_forced_teach_raises_assertiveness_bias() -> None:
    base = derive_group_affect_bias(
        repeat_chain_rate=0.1,
        short_message_ratio=0.2,
        local_answer_ratio=0.2,
        forced_teach_weight=0.0,
    )
    taught = derive_group_affect_bias(
        repeat_chain_rate=0.1,
        short_message_ratio=0.2,
        local_answer_ratio=0.2,
        forced_teach_weight=5.0,
    )
    assert taught["assertiveness_bias"] >= base["assertiveness_bias"]


def test_apply_affect_derived_merges_profile_bias() -> None:
    warmth, assertiveness = apply_affect_derived(0.1, -0.05, {"warmth_bias": 0.12, "assertiveness_bias": 0.2})
    assert warmth == pytest.approx(0.22)
    assert assertiveness == pytest.approx(0.15)


def test_warmth_lowers_answer_threshold() -> None:
    warm = ResolvedPersona(reply_bias=1.0, warmth=0.5)
    cool = ResolvedPersona(reply_bias=1.0, warmth=-0.5)
    base = 10
    assert scaled_answer_threshold(base, warm, in_hosted_activity=False) < scaled_answer_threshold(
        base, cool, in_hosted_activity=False
    )


def test_assertiveness_prefers_cold_answers_when_bold() -> None:
    bold = ResolvedPersona(assertiveness=0.3, chaos_bias=0.0)
    assert answer_popularity_multiplier(1, bold) > answer_popularity_multiplier(10, bold)


def test_merge_affect_refine_placeholder() -> None:
    profile = {"sample": {}, "derived": {"warmth_bias": 0.1, "assertiveness_bias": 0.0}}
    merged = merge_affect_refine_into_profile(profile, None)
    assert merged["sample"]["affect_refine"]["source"] == "none"
