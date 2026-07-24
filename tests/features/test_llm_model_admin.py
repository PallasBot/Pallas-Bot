from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from pallas.product.llm.model_admin import (
    fetch_model_admin_status,
    set_runtime_num_gpu,
    switch_runtime_model,
    unload_runtime_model,
)


@pytest.mark.asyncio
async def test_fetch_model_admin_status_ok(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.local_routing_store.local_routing_store_path",
        lambda: tmp_path / "llm_local_routing.json",
    )
    monkeypatch.setattr(
        "pallas.product.llm.ollama_admin.ollama_runtime_path",
        lambda: tmp_path / "llm_ollama_runtime.json",
    )
    from pallas.product.llm.local_routing_store import clear_local_routing_cache, save_local_routing_document
    from pallas.product.llm.ollama_admin import set_runtime_model_name, set_runtime_num_gpu_value

    clear_local_routing_cache()
    save_local_routing_document({"llm_model": "qwen3.5:9b", "local_multi_model_enabled": True})
    set_runtime_model_name("qwen3.5:9b")
    set_runtime_num_gpu_value(70)
    monkeypatch.setattr(
        "pallas.product.llm.model_admin._resolve_local_provider_base",
        lambda **_kwargs: "http://127.0.0.1:11434",
    )
    monkeypatch.setattr("pallas.product.llm.ollama_admin.ping_ollama", AsyncMock(return_value=True))
    monkeypatch.setattr(
        "pallas.product.llm.providers_store.export_providers_for_api",
        lambda: {
            "providers": [{"id": "local", "kind": "local"}],
            "routing": {"tasks": {"llm_chat": "local"}},
        },
    )

    status = await fetch_model_admin_status()
    assert status["ollama_reachable"] is True
    assert status["ai_reachable"] is True
    assert status["model"] == "qwen3.5:9b"
    assert status["num_gpu"] == 70
    assert status["local_multi_model_enabled"] is True


@pytest.mark.asyncio
async def test_switch_runtime_model_ok(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.local_routing_store.local_routing_store_path",
        lambda: tmp_path / "llm_local_routing.json",
    )
    monkeypatch.setattr(
        "pallas.product.llm.ollama_admin.ollama_runtime_path",
        lambda: tmp_path / "llm_ollama_runtime.json",
    )
    from pallas.product.llm.local_routing_store import clear_local_routing_cache

    clear_local_routing_cache()
    monkeypatch.setattr(
        "pallas.product.llm.model_admin._resolve_local_provider_base",
        lambda **_kwargs: "http://127.0.0.1:11434",
    )
    monkeypatch.setattr("pallas.product.llm.ollama_admin.pull_ollama_model", AsyncMock())
    result = await switch_runtime_model("qwen2.5:7b", pull=False)
    assert result["model"] == "qwen2.5:7b"


@pytest.mark.asyncio
async def test_set_runtime_num_gpu_ok(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.local_routing_store.local_routing_store_path",
        lambda: tmp_path / "llm_local_routing.json",
    )
    monkeypatch.setattr(
        "pallas.product.llm.ollama_admin.ollama_runtime_path",
        lambda: tmp_path / "llm_ollama_runtime.json",
    )
    from pallas.product.llm.local_routing_store import clear_local_routing_cache, save_local_routing_document
    from pallas.product.llm.ollama_admin import set_runtime_model_name

    clear_local_routing_cache()
    save_local_routing_document({"llm_model": "qwen3.5:9b"})
    set_runtime_model_name("qwen3.5:9b")
    result = await set_runtime_num_gpu(24)
    assert result == {"model": "qwen3.5:9b", "num_gpu": 24}


@pytest.mark.asyncio
async def test_unload_runtime_model_ok(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.local_routing_store.local_routing_store_path",
        lambda: tmp_path / "llm_local_routing.json",
    )
    monkeypatch.setattr(
        "pallas.product.llm.ollama_admin.ollama_runtime_path",
        lambda: tmp_path / "llm_ollama_runtime.json",
    )
    from pallas.product.llm.local_routing_store import clear_local_routing_cache, save_local_routing_document
    from pallas.product.llm.ollama_admin import set_runtime_model_name

    clear_local_routing_cache()
    save_local_routing_document({"llm_model": "qwen3.5:9b"})
    set_runtime_model_name("qwen3.5:9b")
    monkeypatch.setattr(
        "pallas.product.llm.model_admin._resolve_local_provider_base",
        lambda **_kwargs: "http://127.0.0.1:11434",
    )
    unload = AsyncMock()
    monkeypatch.setattr("pallas.product.llm.ollama_admin.unload_ollama_model", unload)
    await unload_runtime_model()
    unload.assert_awaited()
