from __future__ import annotations

import pytest

from pallas.product.llm.task_routing import (
    TaskRouteSpec,
    clear_task_route_cache,
    resolve_submit_task_name,
    resolve_task_route,
)


def test_resolve_submit_task_name_defaults() -> None:
    assert resolve_submit_task_name("repeater_select") == "repeater_select"
    assert resolve_submit_task_name(None, "drunk") == "drunk"
    assert resolve_submit_task_name("", None) == "llm_chat"


@pytest.mark.asyncio
async def test_resolve_task_route_explicit_model_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_task_route_cache()

    async def fail_health(**_kwargs):
        raise AssertionError("explicit model should bypass remote route lookup")

    monkeypatch.setattr("pallas.product.llm.task_routing.probe_ai_service_health", fail_health)

    route = await resolve_task_route("llm_chat", explicit_model="qwen3:32b")

    assert route == TaskRouteSpec(
        task="llm_chat",
        resolved_model="qwen3:32b",
        provider_hint=None,
        source="explicit",
        fallback_models=(),
    )


@pytest.mark.asyncio
async def test_resolve_task_route_prefers_ai_health_task_routing_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_task_route_cache()

    async def fake_health(**_kwargs):
        return {
            "ok": True,
            "body": {
                "llm": {
                    "provider_mode": "chain",
                    "task_routing": {"drunk": "local", "llm_chat": "remote"},
                    "local_task_models": {"repeater_select": "qwen2.5:0.5b"},
                }
            },
        }

    async def fail_local(**_kwargs):
        raise AssertionError("health route should be preferred before local-routing fetch")

    async def fake_providers(**_kwargs):
        return {
            "providers": [
                {
                    "id": "local",
                    "kind": "local",
                    "default_model": "qwen3:8b",
                    "task_models": {"drunk": "qwen2.5:0.5b"},
                },
                {
                    "id": "remote",
                    "kind": "remote",
                    "default_model": "deepseek-v4-flash",
                    "task_models": {"llm_chat": "deepseek-v4-flash"},
                },
            ],
            "routing": {"chain_fallback": ["local", "remote"], "tasks": {}},
        }

    monkeypatch.setattr("pallas.product.llm.task_routing.probe_ai_service_health", fake_health)
    monkeypatch.setattr("pallas.product.llm.task_routing.fetch_local_routing_config", fail_local)
    monkeypatch.setattr("pallas.product.llm.model_admin.fetch_providers_config", fake_providers)

    drunk_route = await resolve_task_route("drunk")
    chat_route = await resolve_task_route("llm_chat")

    assert drunk_route == TaskRouteSpec(
        task="drunk",
        resolved_model="qwen2.5:0.5b",
        provider_hint="local",
        source="ai_health",
        fallback_models=("deepseek-v4-flash",),
    )
    assert chat_route == TaskRouteSpec(
        task="llm_chat",
        resolved_model="deepseek-v4-flash",
        provider_hint="remote",
        source="ai_health",
        fallback_models=("qwen3:8b",),
    )


@pytest.mark.asyncio
async def test_resolve_task_route_prefers_ai_health_local_task_models(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_task_route_cache()

    async def fake_health(**_kwargs):
        return {
            "ok": True,
            "body": {
                "llm": {
                    "provider_mode": "local",
                    "local_task_models": {"repeater_select": "qwen3:14b", "llm_chat": "qwen3:8b"},
                }
            },
        }

    async def fail_local(**_kwargs):
        raise AssertionError("health route should be preferred before local-routing fetch")

    monkeypatch.setattr("pallas.product.llm.task_routing.probe_ai_service_health", fake_health)
    monkeypatch.setattr("pallas.product.llm.task_routing.fetch_local_routing_config", fail_local)

    route = await resolve_task_route("repeater_select")

    assert route == TaskRouteSpec(
        task="repeater_select",
        resolved_model="qwen3:14b",
        provider_hint="local",
        source="ai_health",
        fallback_models=(),
    )


@pytest.mark.asyncio
async def test_resolve_task_route_falls_back_to_local_config(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_task_route_cache()

    async def fake_health(**_kwargs):
        return {"ok": False, "body": None}

    async def fake_local(**_kwargs):
        return {
            "llm_model": "qwen3:8b",
            "task_models": {
                "repeater_select": "qwen3:14b",
            },
        }

    monkeypatch.setattr("pallas.product.llm.task_routing.probe_ai_service_health", fake_health)
    monkeypatch.setattr("pallas.product.llm.task_routing.fetch_local_routing_config", fake_local)

    repeater_route = await resolve_task_route("repeater_select")
    chat_route = await resolve_task_route("llm_chat")

    assert repeater_route == TaskRouteSpec(
        task="repeater_select",
        resolved_model="qwen3:14b",
        provider_hint=None,
        source="config",
        fallback_models=(),
    )
    assert chat_route == TaskRouteSpec(
        task="llm_chat",
        resolved_model="qwen3:8b",
        provider_hint=None,
        source="config",
        fallback_models=(),
    )


@pytest.mark.asyncio
async def test_resolve_task_route_chain_expands_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_task_route_cache()

    async def fake_health(**_kwargs):
        return {"ok": False, "body": None}

    async def fake_local(**_kwargs):
        return {
            "llm_model": "primary",
            "task_models": {"llm_chat": "primary"},
            "task_fallback_chains": {"llm_chat": ["fb-1", "fb-2"]},
        }

    monkeypatch.setattr("pallas.product.llm.task_routing.probe_ai_service_health", fake_health)
    monkeypatch.setattr("pallas.product.llm.task_routing.fetch_local_routing_config", fake_local)

    from pallas.product.llm.task_routing import resolve_task_route_chain

    chain = await resolve_task_route_chain("llm_chat")
    assert [item.resolved_model for item in chain] == ["primary", "fb-1", "fb-2"]
    assert chain[0].source == "config"
    assert chain[1].source == "fallback"
