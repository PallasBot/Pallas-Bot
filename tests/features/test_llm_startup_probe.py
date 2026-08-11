from __future__ import annotations

import pytest

from pallas.product.llm.startup_probe import build_llm_startup_fact, probe_ai_service_health


@pytest.mark.asyncio
async def test_probe_ai_service_health_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"status": "ok", "version": "4.0.0-test"}

    async def fake_get(url: str, **kwargs):
        _ = url, kwargs
        return FakeResponse()

    monkeypatch.setattr("pallas.core.shared.utils.HTTPXClient.get", fake_get)
    monkeypatch.setattr(
        "pallas.product.llm.config.get_llm_config",
        lambda: type("Cfg", (), {"ai_server_host": "127.0.0.1", "ai_server_port": 9099})(),
    )
    monkeypatch.setattr(
        "pallas.product.llm.config.llm_server_base_url",
        lambda cfg=None: "http://127.0.0.1:9099",
    )

    result = await probe_ai_service_health()
    assert result["ok"] is True
    assert result["status_code"] == 200


@pytest.mark.asyncio
async def test_probe_ai_service_health_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get(url: str, **kwargs):
        _ = url, kwargs
        raise ConnectionError("refused")

    monkeypatch.setattr("pallas.core.shared.utils.HTTPXClient.get", fake_get)
    monkeypatch.setattr(
        "pallas.product.llm.config.get_llm_config",
        lambda: type("Cfg", (), {"ai_server_host": "127.0.0.1", "ai_server_port": 9099})(),
    )
    monkeypatch.setattr(
        "pallas.product.llm.config.llm_server_base_url",
        lambda cfg=None: "http://127.0.0.1:9099",
    )

    result = await probe_ai_service_health()
    assert result["ok"] is False
    assert "refused" in str(result.get("error", ""))


def test_build_llm_startup_fact_uses_task_endpoint_over_legacy_model() -> None:
    cfg = type("Cfg", (), {"llm_model": "", "llm_chat_enabled": True})()
    endpoint = type("Endpoint", (), {"provider_id": "aliyun", "model": "deepseek-v4-flash"})()

    assert build_llm_startup_fact(cfg, endpoint) == ("ok provider=aliyun model=deepseek-v4-flash chat=enabled")
