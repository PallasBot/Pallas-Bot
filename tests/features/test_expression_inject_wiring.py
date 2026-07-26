from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_llm_chat_expression_suffix_passes_user_text_and_bot_id(monkeypatch) -> None:
    from packages.llm_chat import chat_message as mod

    suffix = AsyncMock(return_value=("\n【表达参考】\n吐槽→太难了。", []))
    monkeypatch.setattr(mod, "build_expression_context_with_entries", suffix)

    result = await mod.build_llm_chat_expression_suffix(10001, "今天加班太离谱了", bot_id=20002)

    assert result == "\n【表达参考】\n吐槽→太难了。"
    suffix.assert_awaited_once()
    assert suffix.await_args.args == (10001, "今天加班太离谱了")
    assert suffix.await_args.kwargs["bot_id"] == 20002


@pytest.mark.asyncio
async def test_repeater_context_appends_expression_reference_and_metadata(monkeypatch) -> None:
    from pallas.product.llm import repeater_persona_context as mod
    from pallas.product.persona.model import ResolvedPersona

    async def fake_resolve_base(*args, **kwargs):
        return "base prompt", 0.8, 64

    async def fake_recent(*args, **kwargs):
        return []

    async def fake_dynamic(*args, **kwargs):
        return ""

    class FakeGroupRepo:
        async def get(self, group_id: int):
            return SimpleNamespace(style_profile=None)

    monkeypatch.setattr(mod, "resolve_repeater_base_system", fake_resolve_base)
    monkeypatch.setattr(mod, "load_recent_bot_plain_replies", fake_recent)
    monkeypatch.setattr(mod, "build_dynamic_expression_hint", fake_dynamic)
    monkeypatch.setattr(mod, "resolve_persona_for_message", AsyncMock(return_value=ResolvedPersona()))
    monkeypatch.setattr(mod, "make_group_config_repository", lambda: FakeGroupRepo())
    monkeypatch.setattr(
        mod,
        "build_expression_context_suffix",
        AsyncMock(return_value="\n【表达参考】\n吐槽→太难了。"),
    )

    bundle = await mod.build_repeater_llm_persona_context(1, 2, "你怎么又这样", purpose="polish_lite")

    assert bundle is not None
    assert "【表达参考】\n吐槽→太难了。" in bundle.system_prompt
    assert bundle.llm_rewrite_metadata["expression_reference_count"] == 1
