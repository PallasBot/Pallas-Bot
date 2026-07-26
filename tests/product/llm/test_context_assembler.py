from __future__ import annotations

import pytest

from pallas.product.llm.assembler.context import assemble_repeater_context


@pytest.mark.asyncio
async def test_assemble_repeater_context_delegates_to_persona_builder(monkeypatch) -> None:
    async def build_context(*args, **kwargs):
        assert args == (1, 2, "测试")
        assert kwargs == {"purpose": "select"}
        return {"system_prompt": "persona"}

    monkeypatch.setattr(
        "pallas.product.llm.assembler.context.build_repeater_llm_persona_context",
        build_context,
    )

    assert await assemble_repeater_context(1, 2, "测试", purpose="select") == {"system_prompt": "persona"}
