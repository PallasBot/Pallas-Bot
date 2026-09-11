"""LLM 出口统一总闸：配置开关与插件全局禁用。"""

from __future__ import annotations

import pytest

from pallas.product.llm.config import LlmConfig


def test_llm_calls_enabled_follows_master_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.availability import llm_calls_enabled

    monkeypatch.setattr("pallas.product.llm.availability.is_llm_plugin_globally_disabled", lambda: False)
    assert llm_calls_enabled(LlmConfig(llm_chat_enabled=False)) is False
    assert llm_calls_enabled(LlmConfig(llm_chat_enabled=True)) is True


def test_llm_calls_enabled_blocked_by_global_disable(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.availability import llm_calls_enabled

    monkeypatch.setattr("pallas.product.llm.availability.is_llm_plugin_globally_disabled", lambda: True)
    assert llm_calls_enabled(LlmConfig(llm_chat_enabled=True)) is False


def test_is_llm_plugin_globally_disabled_reads_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.availability import is_llm_plugin_globally_disabled

    monkeypatch.setattr(
        "packages.help.global_disable.resolve_global_disabled_plugin_names",
        lambda: frozenset({"ollama"}),
    )
    assert is_llm_plugin_globally_disabled() is True


@pytest.mark.asyncio
async def test_complete_chat_message_raises_when_master_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.provider_client import LlmProviderError, complete_chat_message

    with pytest.raises(LlmProviderError):
        await complete_chat_message(
            [{"role": "user", "content": "hi"}],
            model="demo",
            cfg=LlmConfig(llm_chat_enabled=False),
        )


def test_fetch_embeddings_returns_none_when_master_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.knowledge.embedding_client import fetch_embeddings_sync

    assert fetch_embeddings_sync(["hello"], cfg=LlmConfig(llm_chat_enabled=False)) is None


@pytest.mark.asyncio
async def test_scope_gate_uses_runtime_disable(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm.availability import llm_plugin_disabled_for_scope

    async def fake_disabled(plugin_name, group_id=None, bot_id=None, **_kwargs):
        return plugin_name == "llm_chat" and group_id == 42

    monkeypatch.setattr("packages.help.plugin_manager.is_plugin_disabled", fake_disabled)
    assert await llm_plugin_disabled_for_scope(7, 42) is True
    assert await llm_plugin_disabled_for_scope(7, 43) is False
