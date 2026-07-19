from __future__ import annotations

import pytest

from pallas.product.persona.affect_kernel import (
    build_persona_affect_contract,
    build_repeater_persona_affect_system_block,
)


def test_build_repeater_persona_affect_system_block_compact() -> None:
    contract = build_persona_affect_contract(repeated_openers=["其实", "感觉"])
    block = build_repeater_persona_affect_system_block(contract)
    assert "【接话塑形】" in block
    assert "庆典" in block or "客服" in block
    assert "其实" in block


@pytest.mark.asyncio
async def test_build_repeater_llm_persona_context_polish_lite(monkeypatch) -> None:
    from pallas.product.llm import repeater_persona_context as mod

    async def fake_resolve_base(*args, **kwargs):
        return "base prompt", 0.8, 64

    async def fake_recent(*args, **kwargs):
        return ["其实还行", "好的"]

    async def fake_dynamic(*args, **kwargs):
        return "\n【情境触发】测试"

    async def fake_resolve_persona(*args, **kwargs):
        return __import__("pallas.product.persona.model", fromlist=["ResolvedPersona"]).ResolvedPersona()

    class FakeGroupRepo:
        async def get(self, group_id: int):
            return None

    monkeypatch.setattr(mod, "resolve_repeater_base_system", fake_resolve_base)
    monkeypatch.setattr(mod, "load_recent_bot_plain_replies", fake_recent)
    monkeypatch.setattr(mod, "build_dynamic_expression_hint", fake_dynamic)
    monkeypatch.setattr(mod, "resolve_persona_for_message", fake_resolve_persona)
    monkeypatch.setattr(mod, "make_group_config_repository", lambda: FakeGroupRepo())

    bundle = await mod.build_repeater_llm_persona_context(1, 2, "你怎么又这样", purpose="polish_lite")
    assert bundle is not None
    assert "【接话塑形】" in bundle.system_prompt
    assert bundle.llm_rewrite_metadata.get("persona_shaping_active") is True
    assert bundle.llm_rewrite_metadata.get("preserve_colloquial_rewrite") is True
