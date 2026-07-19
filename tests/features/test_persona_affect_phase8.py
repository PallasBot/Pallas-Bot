from __future__ import annotations

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.reply_gate import evaluate_llm_reply_gate, persona_adjusted_min_chars
from pallas.product.persona.activity_ingress import (
    activity_speak_threshold_multiplier,
    classify_activity_level,
)
from pallas.product.persona.affect_axes import derive_bluntness, warmth_behavior_hint
from pallas.product.persona.compile_persona_prompt import build_bot_behavior_prompt, compile_persona_prompt
from pallas.product.persona.model import ResolvedPersona
from pallas.product.persona.preset_layers import PresetLayers, compile_preset_layers_prompt, extract_preset_layers


def test_derive_bluntness_prefers_harsh_over_polite() -> None:
    harsh = derive_bluntness(assertiveness=0.2, harsh_msg_ratio=0.4, polite_msg_ratio=0.0)
    polite = derive_bluntness(assertiveness=0.0, harsh_msg_ratio=0.0, polite_msg_ratio=0.35)
    assert harsh > polite


def test_warmth_behavior_hint_covers_mid_band() -> None:
    assert "中性" in warmth_behavior_hint(0.0)
    assert warmth_behavior_hint(0.1)


def test_build_bot_behavior_prompt_mid_warmth_not_empty() -> None:
    persona = ResolvedPersona(warmth=0.05, assertiveness=-0.02, bluntness=0.03)
    prompt = build_bot_behavior_prompt(persona)
    assert "中性" in prompt
    assert "主张适中" in prompt
    assert "直率与礼貌均衡" in prompt


def test_persona_adjusted_min_chars_cold_persona_stricter() -> None:
    cold = ResolvedPersona(warmth=-0.3, assertiveness=-0.2)
    warm = ResolvedPersona(warmth=0.3, assertiveness=0.2)
    assert persona_adjusted_min_chars(2, cold) > persona_adjusted_min_chars(2, warm)


def test_reply_gate_uses_persona_min_chars() -> None:
    cfg = LlmConfig(llm_reply_gate_enabled=True, llm_reply_gate_min_chars=2)
    cold = ResolvedPersona(warmth=-0.35, assertiveness=-0.1)
    warm = ResolvedPersona(warmth=0.35, assertiveness=0.1)
    assert evaluate_llm_reply_gate("好", cfg=cfg, persona=cold) == "skip"
    assert evaluate_llm_reply_gate("好", cfg=cfg, persona=warm) == "proceed"


def test_classify_activity_level() -> None:
    assert classify_activity_level(1.5) == "quiet"
    assert classify_activity_level(5.0) == "normal"
    assert classify_activity_level(10.0) == "active"


def test_activity_speak_threshold_multiplier() -> None:
    assert activity_speak_threshold_multiplier("quiet") > activity_speak_threshold_multiplier("active")


def test_compile_preset_layers_prompt() -> None:
    layers = PresetLayers(knowledges=["罗德岛"], relationships=["博士：信任"])
    prompt = compile_preset_layers_prompt(layers)
    assert "<<STATS:preset_layers>>" in prompt
    assert "罗德岛" in prompt
    assert "博士" in prompt


def test_extract_preset_layers_merges_bot_and_sample() -> None:
    layers = extract_preset_layers(
        {"knowledges": ["A"], "relationships": ["R1"]},
        {"layers": {"knowledges": ["B"], "relationships": ["R2"]}},
    )
    assert "A" in layers.knowledges
    assert "B" in layers.knowledges
    assert "R1" in layers.relationships
    assert "R2" in layers.relationships


def test_compile_persona_prompt_includes_preset_layers() -> None:
    persona = ResolvedPersona()
    bundle = compile_persona_prompt(
        persona,
        None,
        bot_id=1,
        bot_persona={"knowledges": ["测试知识"], "relationships": ["测试关系"]},
    )
    assert "<<STATS:preset_layers>>" in bundle.sections.preset_layers
    assert "测试知识" in bundle.system
