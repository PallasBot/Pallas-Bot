from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_repeater_context_does_not_append_expression_reference(monkeypatch) -> None:
    from pallas.product.llm import repeater_persona_context as mod
    from pallas.product.persona.model import ResolvedPersona

    async def fake_resolve_base(*args, **kwargs):
        return "base prompt", 0.8, 64

    async def fake_recent(*args, **kwargs):
        return []

    dynamic = AsyncMock(return_value="\n【情境触发】测试")
    expressions = AsyncMock(return_value="\n【表达参考】\n吐槽→太难了。")

    monkeypatch.setattr(mod, "resolve_repeater_base_system", fake_resolve_base)
    monkeypatch.setattr(mod, "load_recent_bot_plain_replies", fake_recent)
    monkeypatch.setattr(mod, "build_dynamic_expression_hint", dynamic, raising=False)
    monkeypatch.setattr(mod, "resolve_persona_for_message", AsyncMock(return_value=ResolvedPersona()))
    monkeypatch.setattr(
        mod,
        "build_expression_context_suffix",
        expressions,
        raising=False,
    )

    bundle = await mod.build_repeater_llm_persona_context(1, 2, "你怎么又这样", purpose="polish_lite")

    assert bundle is not None
    assert "【表达参考】" not in bundle.system_prompt
    assert "【情境触发】" not in bundle.system_prompt
    assert "expression_reference_count" not in bundle.llm_rewrite_metadata
    assert "dynamic_expression_hint" not in bundle.llm_rewrite_metadata
    expressions.assert_not_awaited()
    dynamic.assert_not_awaited()
