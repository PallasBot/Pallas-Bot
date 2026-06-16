from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.features.persona.affect_baseline import merge_affect_refine_into_profile
from src.features.persona.affect_refine import affect_refine_from_ai_response, refine_group_style_affect
from src.features.persona.affect_refine_client import build_affect_refine_payload, collect_affect_refine_samples


def test_collect_affect_refine_samples_skips_empty() -> None:
    messages = [SimpleNamespace(plain_text=""), SimpleNamespace(plain_text="谢谢")]
    samples = collect_affect_refine_samples(messages, limit=5)
    assert samples == ["谢谢"]


def test_build_affect_refine_payload_includes_hints() -> None:
    profile = {
        "sample": {"message_count": 40, "answer_count": 8, "window_hours": 168},
        "raw": {
            "repeat_chain_rate": 0.1,
            "local_answer_ratio": 0.2,
            "affect_tone": {"civility_score": 0.3},
        },
        "derived": {
            "warmth_bias": 0.05,
            "assertiveness_bias": 0.1,
            "length_pref": "short",
            "chaos_bias": 0.12,
        },
    }
    payload = build_affect_refine_payload(profile, group_id=99, message_samples=["草"])
    assert payload["group_id"] == 99
    assert payload["message_samples"] == ["草"]
    assert isinstance(payload["hints"], list)


def test_affect_refine_from_ai_response_low_confidence_zeros_delta() -> None:
    refine = affect_refine_from_ai_response(
        {"warmth_delta": 0.2, "assertiveness_delta": 0.15, "confidence": 0.2, "summary": "x"}
    )
    assert refine["warmth_delta"] == 0.0
    assert refine["assertiveness_delta"] == 0.0
    assert refine["source"] == "llm"


@pytest.mark.asyncio
async def test_refine_group_style_affect_disabled() -> None:
    profile = {"sample": {}, "derived": {"warmth_bias": 0.1, "assertiveness_bias": 0.0}}
    merged = await refine_group_style_affect(profile, group_id=1, message_samples=["a"])
    assert merged["sample"]["affect_refine"]["source"] == "none"


@pytest.mark.asyncio
async def test_refine_group_style_affect_calls_ai(monkeypatch) -> None:
    from src.features.persona import affect_refine as mod

    monkeypatch.setattr(mod, "llm_affect_refine_enabled", lambda: True)

    async def fake_post(payload):
        return {"warmth_delta": 0.05, "assertiveness_delta": 0.02, "confidence": 0.8, "summary": "ok"}

    monkeypatch.setattr(mod, "post_affect_refine", fake_post)

    profile = {
        "sample": {"message_count": 40, "answer_count": 8},
        "raw": {"repeat_chain_rate": 0.1, "local_answer_ratio": 0.2},
        "derived": {"warmth_bias": 0.1, "assertiveness_bias": 0.0, "length_pref": "short", "chaos_bias": 0.1},
    }
    merged = await refine_group_style_affect(profile, group_id=7, message_samples=["谢谢"])
    assert merged["sample"]["affect_refine"]["source"] == "llm"
    assert merged["derived"]["warmth_bias"] == pytest.approx(0.15)
    assert merged["sample"]["affect_refine"]["summary"] == "ok"


def test_merge_affect_refine_stores_confidence() -> None:
    profile = {"sample": {}, "derived": {"warmth_bias": 0.0, "assertiveness_bias": 0.0}}
    merged = merge_affect_refine_into_profile(
        profile,
        {
            "source": "llm",
            "warmth_delta": 0.1,
            "assertiveness_delta": 0.0,
            "confidence": 0.75,
            "summary": "test",
            "updated_at": 1,
        },
    )
    assert merged["sample"]["affect_refine"]["confidence"] == 0.75
    assert merged["sample"]["affect_refine"]["summary"] == "test"
