from __future__ import annotations

from pallas.product.persona.shaping_observe import (
    build_persona_shaping_summary,
    extract_persona_sections_from_system_prompt,
)


def test_extract_persona_sections_from_system_prompt() -> None:
    system = (
        "base\n\n【本轮牛格塑形】\n- 像顺口接话\n\n"
        "【情境触发】提到「开黑」时，语气可稍软\n\n"
        "【本轮表达去重】\n- 最近别再用这些开头：其实"
    )
    sections = extract_persona_sections_from_system_prompt(system)

    assert "- 像顺口接话" in sections["【本轮牛格塑形】"]
    assert "开黑" in sections["【情境触发】"]
    assert "其实" in sections["【本轮表达去重】"]


def test_build_persona_shaping_summary_prefers_metadata() -> None:
    summary = build_persona_shaping_summary(
        {
            "task": "llm_chat",
            "persona_shaping_active": True,
            "persona_affect_block": "【本轮牛格塑形】\n- 优先短句",
            "variation_hint": "【本轮表达去重】\n- 最近解释偏满",
        },
        system_prompt="ignored",
    )

    assert summary["persona_shaping_active"] is True
    assert summary["lines"] == ["优先短句"]
    assert "最近解释偏满" in summary["variation_hint"]
    assert summary["source_task"] == "llm_chat"
    assert "@ 闲聊" in summary["compare_note"]
