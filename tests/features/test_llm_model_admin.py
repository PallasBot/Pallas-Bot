from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pallas.product.llm.model_admin import (
    fetch_model_admin_status,
    set_runtime_num_gpu,
    switch_runtime_model,
    unload_runtime_model,
)


@pytest.mark.asyncio
async def test_fetch_model_admin_status_ok(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.probe_ai_service_health",
        AsyncMock(
            return_value={
                "ok": True,
                "url": "http://127.0.0.1:9099/health",
                "error": "",
                "body": {
                    "llm": {
                        "provider_mode": "chain",
                        "provider_status": [
                            {"id": "local", "kind": "local", "configured": True, "reachable": True},
                        ],
                        "categorizer_enabled": True,
                        "categorizer_model": "qwen2.5:0.5b",
                        "tools_selective": True,
                    },
                },
            },
        ),
    )
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"model": "qwen3.5:9b", "num_gpu": 70}
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.HTTPXClient.get",
        AsyncMock(return_value=response),
    )
    status = await fetch_model_admin_status()
    assert status["ai_reachable"] is True
    assert status["model"] == "qwen3.5:9b"
    assert status["num_gpu"] == 70
    assert status["provider_mode"] == "chain"
    assert status["provider_status"][0]["id"] == "local"
    assert status["categorizer_enabled"] is True


@pytest.mark.asyncio
async def test_switch_runtime_model_ok(monkeypatch: pytest.MonkeyPatch):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"model": "qwen2.5:7b", "num_gpu": 70}
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.HTTPXClient.put",
        AsyncMock(return_value=response),
    )
    result = await switch_runtime_model("qwen2.5:7b", pull=False)
    assert result == {"model": "qwen2.5:7b", "num_gpu": 70}


@pytest.mark.asyncio
async def test_set_runtime_num_gpu_ok(monkeypatch: pytest.MonkeyPatch):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"model": "qwen3.5:9b", "num_gpu": 24}
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.HTTPXClient.post",
        AsyncMock(return_value=response),
    )
    result = await set_runtime_num_gpu(24)
    assert result == {"model": "qwen3.5:9b", "num_gpu": 24}


@pytest.mark.asyncio
async def test_unload_runtime_model_ok(monkeypatch: pytest.MonkeyPatch):
    response = MagicMock()
    response.status_code = 200
    monkeypatch.setattr(
        "pallas.product.llm.model_admin.HTTPXClient.post",
        AsyncMock(return_value=response),
    )
    await unload_runtime_model()
