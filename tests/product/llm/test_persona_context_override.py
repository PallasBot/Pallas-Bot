from types import SimpleNamespace

import pytest

from pallas.product.llm import persona_context


@pytest.mark.asyncio
async def test_prompt_override_wins_over_configured_path(monkeypatch):
    seen = {}

    async def fake_compile(*args, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            system="compiled",
            metadata=SimpleNamespace(persona={}),
        )

    monkeypatch.setattr(persona_context, "compile_persona_prompt_for", fake_compile)
    token = persona_context.llm_chat_prompt_override.set("variant prompt")
    try:
        await persona_context.build_persona_llm_context(
            10001,
            20002,
            "hello",
            base_system_path="configured.txt",
        )
    finally:
        persona_context.llm_chat_prompt_override.reset(token)

    assert seen["base_system"] == "variant prompt"
    assert seen["base_system_path"] == "configured.txt"
    assert persona_context.llm_chat_prompt_override.get() is None


@pytest.mark.asyncio
async def test_prompt_override_is_absent_for_normal_calls(monkeypatch):
    seen = {}

    async def fake_compile(*args, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(system="compiled", metadata=SimpleNamespace(persona={}))

    monkeypatch.setattr(persona_context, "compile_persona_prompt_for", fake_compile)
    await persona_context.build_persona_llm_context(
        10001,
        20002,
        "hello",
        base_system_path="configured.txt",
    )

    assert seen["base_system"] is None
    assert seen["base_system_path"] == "configured.txt"
