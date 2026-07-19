from pallas.product.persona.affect_kernel import (
    build_persona_affect_contract,
    build_persona_affect_system_block,
    group_flavor_summary_from_style_snapshot,
)
from pallas.product.persona.model import ResolvedPersona


def test_build_persona_affect_system_block_includes_stance_and_length() -> None:
    contract = build_persona_affect_contract(
        ResolvedPersona(length_pref="short", warmth=0.2, chaos_bias=0.2),
        group_flavor_summary="本群风格：群消息偏短、复读链与短句常见",
    )
    block = build_persona_affect_system_block(contract)
    assert "【本轮牛格塑形】" in block
    assert "本群风格" in block
    assert "短口语" in block
    assert "句长预算" in block
    assert "避免腔调" in block


def test_build_persona_affect_system_block_never_empty_for_default_persona() -> None:
    contract = build_persona_affect_contract(ResolvedPersona())
    block = build_persona_affect_system_block(contract)
    assert "【本轮牛格塑形】" in block
    assert "顺口接话" in block


def test_group_flavor_summary_from_style_snapshot() -> None:
    summary = group_flavor_summary_from_style_snapshot({
        "ready": True,
        "hints": ["群消息偏短", "复读链与短句常见"],
    })
    assert summary == "本群风格：群消息偏短、复读链与短句常见"
