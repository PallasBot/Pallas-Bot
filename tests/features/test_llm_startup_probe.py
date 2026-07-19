from __future__ import annotations

import pytest

from pallas.product.llm.startup_probe import ai_api_version_compatible, parse_api_version, probe_ai_service_health


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


def test_parse_api_version() -> None:
    assert parse_api_version("4.0.0") == (4, 0, 0)
    assert parse_api_version("4.0.0-beta") == (4, 0, 0)
    assert parse_api_version("") is None


def test_ai_api_version_compatible() -> None:
    assert ai_api_version_compatible("4.0.0") is True
    assert ai_api_version_compatible("4.1.0") is True
    assert ai_api_version_compatible("3.9.9") is False
    assert ai_api_version_compatible(None) is True
