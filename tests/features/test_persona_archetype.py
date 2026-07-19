from __future__ import annotations

import pytest

from pallas.product.persona.affect_lexicon import scan_content_tags
from pallas.product.persona.affect_triggers import (
    apply_affect_trigger_bias,
    trigger_phrase_weight_multiplier,
)
from pallas.product.persona.auto import archetype_for_bot_id, derive_persona_from_bot_id
from pallas.product.persona.model import ResolvedPersona
from pallas.product.persona.scorer import content_tag_weight_multiplier, message_weight_multiplier


def test_archetype_for_bot_id_cycles() -> None:
    assert archetype_for_bot_id(10001) == "polite"
    assert archetype_for_bot_id(10002) == "terse"
    assert archetype_for_bot_id(10003) == "chaotic"


def test_derive_persona_applies_archetype_overlay() -> None:
    enabled = derive_persona_from_bot_id(10002, archetype_enabled=True)
    disabled = derive_persona_from_bot_id(10002, archetype_enabled=False)
    assert enabled.archetype == "terse"
    assert enabled.preset_label == "寡言"
    assert enabled.tone == "terse"
    assert disabled.archetype == ""
    assert disabled.preset_label == "自动"


def test_scan_content_tags_detects_lexicon_hits() -> None:
    polite_hit, harsh_hit = scan_content_tags("谢谢大佬")
    assert polite_hit is True
    assert harsh_hit is False
    polite_hit, harsh_hit = scan_content_tags("卧槽这也太离谱")
    assert polite_hit is False
    assert harsh_hit is True


def test_content_tag_weight_multiplier_boosts_harsh_in_harsh_group() -> None:
    heavy = content_tag_weight_multiplier("卧槽", harsh_msg_ratio=0.5, polite_msg_ratio=0.0)
    light = content_tag_weight_multiplier("卧槽", harsh_msg_ratio=0.0, polite_msg_ratio=0.0)
    neutral = content_tag_weight_multiplier("普通一句", harsh_msg_ratio=0.5, polite_msg_ratio=0.0)
    assert heavy > light
    assert neutral == pytest.approx(1.0)


def test_message_weight_multiplier_prefers_harsh_candidates_in_harsh_group() -> None:
    persona = ResolvedPersona(harsh_msg_ratio=0.35, polite_msg_ratio=0.0)
    harsh_weight = message_weight_multiplier("卧槽牛", persona)
    plain_weight = message_weight_multiplier("今天天气不错", persona)
    assert harsh_weight > plain_weight


def test_trigger_phrase_weight_multiplier_boosts_matching_candidate() -> None:
    triggers = [{"phrase": "博士", "weight": 1.0}]
    matched = trigger_phrase_weight_multiplier("好的博士", triggers)
    plain = trigger_phrase_weight_multiplier("好的", triggers)
    assert matched > plain


def test_apply_affect_trigger_bias_offsets_persona() -> None:
    persona = ResolvedPersona(warmth=0.0, assertiveness=0.0)
    triggers = [{"phrase": "加油", "warmth_delta": 0.2, "assertiveness_delta": 0.1, "weight": 1.0}]
    shifted = apply_affect_trigger_bias(persona, "大家加油啊", triggers)
    assert shifted.warmth > persona.warmth
    assert shifted.assertiveness > persona.assertiveness


@pytest.mark.asyncio
async def test_resolve_persona_for_message_merges_group_tone_ratios(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.persona.loader import invalidate_persona_cache, resolve_persona_for_message

    class DummyGroupRepo:
        async def get(self, key, ignore_cache=False):  # noqa: ARG002
            return type(
                "GroupCfg",
                (),
                {
                    "style_profile": {
                        "derived": {"reply_bias_mul": 1.0},
                        "raw": {"affect_tone": {"harsh_msg_ratio": 0.42, "polite_msg_ratio": 0.18}},
                        "sample": {"affect_triggers": []},
                    }
                },
            )()

    class DummyBotRepo:
        async def get(self, key, ignore_cache=False):  # noqa: ARG002
            return type("BotCfg", (), {"group_style_enabled": True})()

    monkeypatch.setattr(
        "pallas.product.persona.loader.derive_persona_from_bot_id",
        lambda _bid, archetype_enabled=True: ResolvedPersona(),
    )
    monkeypatch.setattr("pallas.product.persona.loader.make_group_config_repository", lambda: DummyGroupRepo())
    monkeypatch.setattr("pallas.product.persona.loader.make_bot_config_repository", lambda: DummyBotRepo())

    invalidate_persona_cache()
    resolved = await resolve_persona_for_message(10001, 20002, "普通消息")

    assert resolved.harsh_msg_ratio == pytest.approx(0.42)
    assert resolved.polite_msg_ratio == pytest.approx(0.18)
