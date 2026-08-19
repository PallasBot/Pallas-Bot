from __future__ import annotations

import pytest

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.task_routing import (
    TaskRouteSpec,
    clear_task_route_cache,
    resolve_submit_task_name,
    resolve_task_route,
)


def test_resolve_submit_task_name_defaults() -> None:
    assert resolve_submit_task_name("drunk") == "drunk"
    assert resolve_submit_task_name(None, "drunk") == "drunk"
    assert resolve_submit_task_name("", None) == "llm_chat"


@pytest.mark.asyncio
async def test_resolve_task_route_explicit_model_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_task_route_cache()
    route = await resolve_task_route("llm_chat", explicit_model="qwen3:32b")
    assert route == TaskRouteSpec(
        task="llm_chat",
        resolved_model="qwen3:32b",
        provider_hint=None,
        source="explicit",
        fallback_models=(),
    )


@pytest.mark.asyncio
async def test_resolve_task_route_bot_kernel_uses_config_model(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_task_route_cache()
    cfg = LlmConfig(llm_model="kernel-demo", llm_base_url="http://x/v1")
    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", lambda: cfg)
    monkeypatch.setattr(
        "pallas.product.llm.providers_store.resolve_endpoint_for_task",
        lambda *_args, **_kwargs: None,
    )
    route = await resolve_task_route("llm_chat")
    assert route == TaskRouteSpec(
        task="llm_chat",
        resolved_model="kernel-demo",
        provider_hint="bot_kernel",
        source="config",
        fallback_models=(),
    )


@pytest.mark.asyncio
async def test_resolve_task_route_bot_kernel_uses_providers_store(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    clear_task_route_cache()
    store = tmp_path / "llm_providers.json"
    monkeypatch.setattr("pallas.product.llm.providers_store.providers_store_path", lambda: store)
    monkeypatch.setattr("pallas.product.llm.providers_store._read_ai_providers_toml", lambda: None)
    from pallas.product.llm.providers_store import clear_providers_store_cache, save_providers_document

    clear_providers_store_cache()
    save_providers_document({
        "providers": [
            {
                "id": "primary",
                "kind": "remote",
                "base_url": "https://api.example.com/v1",
                "api_key": "sk-primary",
                "default_model": "model-a",
                "task_models": {"llm_chat": "model-a"},
            },
            {
                "id": "backup",
                "kind": "remote",
                "base_url": "https://backup.example.com/v1",
                "api_key": "sk-backup",
                "default_model": "model-b",
                "task_models": {"llm_chat": "model-b"},
            },
        ],
        "routing": {"chain_fallback": ["primary", "backup"], "tasks": {"llm_chat": "primary"}},
    })
    cfg = LlmConfig(llm_model="", llm_base_url="")
    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", lambda: cfg)

    route = await resolve_task_route("llm_chat")
    assert route == TaskRouteSpec(
        task="llm_chat",
        resolved_model="model-a",
        provider_hint="primary",
        source="config",
        fallback_models=("model-b",),
    )


@pytest.mark.asyncio
async def test_resolve_task_route_chain_expands_provider_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    clear_task_route_cache()
    store = tmp_path / "llm_providers.json"
    monkeypatch.setattr("pallas.product.llm.providers_store.providers_store_path", lambda: store)
    monkeypatch.setattr("pallas.product.llm.providers_store._read_ai_providers_toml", lambda: None)
    from pallas.product.llm.providers_store import clear_providers_store_cache, save_providers_document
    from pallas.product.llm.task_routing import resolve_task_route_chain

    clear_providers_store_cache()
    save_providers_document({
        "providers": [
            {
                "id": "primary",
                "kind": "remote",
                "base_url": "https://api.example.com/v1",
                "api_key": "sk-primary",
                "default_model": "primary",
            },
            {
                "id": "fb1",
                "kind": "remote",
                "base_url": "https://fb1.example.com/v1",
                "api_key": "sk-1",
                "default_model": "fb-1",
            },
            {
                "id": "fb2",
                "kind": "remote",
                "base_url": "https://fb2.example.com/v1",
                "api_key": "sk-2",
                "default_model": "fb-2",
            },
        ],
        "routing": {
            "chain_fallback": ["primary", "fb1", "fb2"],
            "tasks": {"llm_chat": "primary"},
        },
    })
    cfg = LlmConfig(llm_model="", llm_base_url="")
    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", lambda: cfg)

    chain = await resolve_task_route_chain("llm_chat")
    assert [item.resolved_model for item in chain] == ["primary", "fb-1", "fb-2"]
    assert chain[0].source == "config"
    assert chain[1].source == "fallback"


@pytest.mark.asyncio
async def test_resolve_task_route_same_provider_tier_backup_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    clear_task_route_cache()
    store = tmp_path / "llm_providers.json"
    monkeypatch.setattr("pallas.product.llm.providers_store.providers_store_path", lambda: store)
    monkeypatch.setattr("pallas.product.llm.providers_store._read_ai_providers_toml", lambda: None)
    from pallas.product.llm.providers_store import clear_providers_store_cache, save_providers_document

    clear_providers_store_cache()
    save_providers_document({
        "providers": [
            {
                "id": "ds",
                "kind": "remote",
                "base_url": "https://api.example.com/v1",
                "api_key": "sk-ds",
                "default_model": "flash",
                "task_models": {"llm_chat": "flash"},
            },
        ],
        "routing": {
            "chain_fallback": ["ds"],
            "tasks": {"llm_chat": "ds"},
            "tier_backups": {"high": "ds"},
            "tier_backup_models": {"high": "reasoner"},
        },
    })
    cfg = LlmConfig(llm_model="", llm_base_url="")
    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", lambda: cfg)

    route = await resolve_task_route("llm_chat")
    assert route.resolved_model == "flash"
    assert route.provider_hint == "ds"
    assert route.fallback_models == ("reasoner",)


@pytest.mark.asyncio
async def test_turn_decision_uses_low_tier_provider_route(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    clear_task_route_cache()
    store = tmp_path / "llm_providers.json"
    monkeypatch.setattr("pallas.product.llm.providers_store.providers_store_path", lambda: store)
    monkeypatch.setattr("pallas.product.llm.providers_store._read_ai_providers_toml", lambda: None)
    from pallas.product.llm.providers_store import clear_providers_store_cache, save_providers_document

    clear_providers_store_cache()
    save_providers_document({
        "providers": [
            {
                "id": "fast",
                "kind": "remote",
                "base_url": "https://fast.example.com/v1",
                "api_key": "sk-fast",
                "default_model": "fast-model",
                "task_models": {"turn_decision": "decision-model"},
            }
        ],
        "routing": {
            "chain_fallback": ["fast"],
            "tasks": {"turn_decision": "fast"},
            "tier_backups": {"low": "fast"},
            "tier_backup_models": {"low": "decision-backup"},
        },
    })
    monkeypatch.setattr(
        "pallas.product.llm.config.get_llm_config",
        lambda: LlmConfig(llm_model="", llm_base_url=""),
    )

    route = await resolve_task_route("turn_decision")

    assert route.resolved_model == "decision-model"
    assert route.provider_hint == "fast"
    assert route.fallback_models == ("decision-backup",)
