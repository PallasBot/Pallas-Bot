from __future__ import annotations

import time

import pytest

from pallas.product.persona.affect_baseline import merge_affect_refine_into_profile
from pallas.product.persona.affect_triggers import (
    apply_affect_trigger_bias,
    decay_affect_triggers,
    merge_affect_triggers,
    scan_affect_trigger_bias,
)
from pallas.product.persona.model import ResolvedPersona


def test_merge_affect_triggers_dedupes_phrase() -> None:
    now = int(time.time())
    previous = [
        {
            "phrase": "？？？",
            "warmth_delta": -0.02,
            "assertiveness_delta": 0.03,
            "expires_at": now + 3600,
            "weight": 0.8,
        }
    ]
    incoming = [{"phrase": "？？？", "warmth_delta": -0.01, "assertiveness_delta": 0.05, "ttl_hours": 24}]
    merged = merge_affect_triggers(previous, incoming, now_ts=now)
    assert len(merged) == 1
    assert merged[0]["weight"] > 0.8


def test_decay_affect_triggers_drops_expired() -> None:
    now = int(time.time())
    kept = decay_affect_triggers(
        [{"phrase": "旧", "expires_at": now - 10, "weight": 1.0}],
        now_ts=now,
    )
    assert kept == []


def test_scan_affect_trigger_bias_matches_substring() -> None:
    now = int(time.time())
    triggers = [
        {
            "phrase": "？？？",
            "warmth_delta": -0.1,
            "assertiveness_delta": 0.2,
            "expires_at": now + 3600,
            "weight": 1.0,
        }
    ]
    warmth, assertiveness = scan_affect_trigger_bias("这也太离谱了吧？？？", triggers)
    assert warmth < 0
    assert assertiveness > 0


def test_apply_affect_trigger_bias_updates_persona() -> None:
    persona = ResolvedPersona(warmth=0.0, assertiveness=0.0)
    now = int(time.time())
    adjusted = apply_affect_trigger_bias(
        persona,
        "谢谢",
        [{"phrase": "谢谢", "warmth_delta": 0.15, "assertiveness_delta": 0.0, "expires_at": now + 3600, "weight": 1.0}],
    )
    assert adjusted.warmth > persona.warmth


def test_merge_affect_refine_stores_triggers() -> None:
    from pallas.product.persona.affect_triggers import apply_affect_refine_triggers_to_profile

    now = int(time.time())
    profile = {"sample": {}, "derived": {"warmth_bias": 0.0, "assertiveness_bias": 0.0}}
    refine = {
        "source": "llm",
        "warmth_delta": 0.0,
        "assertiveness_delta": 0.0,
        "confidence": 0.9,
        "summary": "",
        "updated_at": now,
        "triggers": [{"phrase": "草", "warmth_delta": 0.0, "assertiveness_delta": 0.1, "ttl_hours": 48}],
    }
    merged = apply_affect_refine_triggers_to_profile(
        merge_affect_refine_into_profile(profile, refine),
        refine,
    )
    triggers = merged["sample"]["affect_triggers"]
    assert len(triggers) == 1
    assert triggers[0]["phrase"] == "草"


@pytest.mark.asyncio
async def test_resolve_persona_for_message_applies_triggers(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.persona.loader import invalidate_persona_cache, resolve_persona_for_message

    invalidate_persona_cache()

    async def fake_resolve_persona(bot_id: int, group_id: int | None = None):
        return ResolvedPersona(warmth=0.0, assertiveness=0.0)

    async def fake_load_triggers(group_id: int):
        now = int(time.time())
        return [
            {
                "phrase": "离谱",
                "warmth_delta": 0.0,
                "assertiveness_delta": 0.2,
                "expires_at": now + 3600,
                "weight": 1.0,
            }
        ]

    monkeypatch.setattr("pallas.product.persona.loader.resolve_persona", fake_resolve_persona)
    monkeypatch.setattr("pallas.product.persona.loader.load_affect_triggers", fake_load_triggers)

    persona = await resolve_persona_for_message(1, 2, "这也太离谱了")
    assert persona.assertiveness > 0.0
