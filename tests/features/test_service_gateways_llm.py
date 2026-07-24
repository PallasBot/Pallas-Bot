import pytest

from pallas.core.shared.service_probe import format_probe_line
from pallas.product.service_gateways.llm_probe import LLM_CATEGORY, normalize_llm_probe_error, probe_llm_service
from pallas.product.service_gateways.registry import registered_service_probe_names


@pytest.mark.asyncio
async def test_probe_llm_when_all_switches_off(monkeypatch) -> None:
    class FakeCfg:
        llm_chat_enabled = False
        llm_fallback_enabled = False
        llm_polish_enabled = False
        llm_select_enabled = False
        llm_polish_lite_enabled = False

    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", lambda: FakeCfg())
    results = await probe_llm_service(timeout_sec=5.0)
    assert len(results) == 1
    assert results[0].category == LLM_CATEGORY
    assert results[0].ok is False
    assert "均为关" in (results[0].error or "")
    assert results[0].capability_id == "llm.chat"
    assert results[0].capability_group == "dialogue"
    assert results[0].runtime_type == "llm"
    assert results[0].failure_class == "runtime_disabled"
    assert results[0].health_state == "unknown"


@pytest.mark.asyncio
async def test_probe_llm_ok_without_url(monkeypatch) -> None:
    class FakeCfg:
        llm_chat_enabled = True
        llm_fallback_enabled = False
        llm_polish_enabled = False
        llm_select_enabled = False
        llm_polish_lite_enabled = False

    async def fake_provider(*, timeout_sec: float = 3.0):
        _ = timeout_sec
        return {
            "ok": True,
            "configured": True,
            "url": "http://127.0.0.1:11434/v1/models",
            "status_code": 200,
            "error": "",
        }

    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", lambda: FakeCfg())
    monkeypatch.setattr(
        "pallas.product.llm.startup_probe.probe_llm_provider",
        fake_provider,
    )
    results = await probe_llm_service(timeout_sec=5.0)
    assert len(results) == 1
    assert results[0].ok is True
    assert results[0].error is None
    assert results[0].runtime_state == "healthy"
    assert results[0].capability_id == "llm.chat"
    assert results[0].capability_group == "dialogue"
    assert results[0].runtime_type == "llm"
    assert results[0].health_state == "healthy"
    assert results[0].site == "Provider"
    line = format_probe_line(results[0])
    assert "127.0.0.1" not in line
    assert "Provider 可达" in line


@pytest.mark.asyncio
async def test_probe_llm_failure_without_url(monkeypatch) -> None:
    class FakeCfg:
        llm_chat_enabled = True
        llm_fallback_enabled = False
        llm_polish_enabled = False
        llm_select_enabled = False
        llm_polish_lite_enabled = False

    async def fake_provider(*, timeout_sec: float = 3.0):
        _ = timeout_sec
        return {
            "ok": False,
            "configured": True,
            "url": "http://127.0.0.1:11434/v1/models",
            "status_code": None,
            "error": "ConnectError: connection refused",
        }

    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", lambda: FakeCfg())
    monkeypatch.setattr(
        "pallas.product.llm.startup_probe.probe_llm_provider",
        fake_provider,
    )
    results = await probe_llm_service(timeout_sec=5.0)
    assert len(results) == 1
    assert results[0].ok is False
    assert results[0].error == "连接失败"
    assert results[0].runtime_state == "degraded"
    assert results[0].capability_id == "llm.chat"
    assert results[0].capability_group == "dialogue"
    assert results[0].runtime_type == "llm"
    assert results[0].failure_class == "connection_failed"
    assert results[0].health_state == "unhealthy"
    line = format_probe_line(results[0])
    assert "127.0.0.1" not in line
    assert "连接失败" in line


@pytest.mark.asyncio
async def test_probe_llm_http_failure_uses_runtime_normalizer(monkeypatch) -> None:
    class FakeCfg:
        llm_chat_enabled = True
        llm_fallback_enabled = False
        llm_polish_enabled = False
        llm_select_enabled = False
        llm_polish_lite_enabled = False

    async def fake_provider(*, timeout_sec: float = 3.0):
        _ = timeout_sec
        return {
            "ok": False,
            "configured": True,
            "url": "http://127.0.0.1:11434/v1/models",
            "status_code": 503,
            "error": "HTTP 503",
        }

    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", lambda: FakeCfg())
    monkeypatch.setattr(
        "pallas.product.llm.startup_probe.probe_llm_provider",
        fake_provider,
    )
    results = await probe_llm_service(timeout_sec=5.0)
    assert len(results) == 1
    assert results[0].ok is False
    assert results[0].runtime_state == "degraded"
    assert results[0].runtime_detail is None
    assert results[0].failure_class == "upstream_http_error"
    assert results[0].health_state == "unhealthy"


@pytest.mark.asyncio
async def test_probe_llm_not_configured(monkeypatch) -> None:
    class FakeCfg:
        llm_chat_enabled = True
        llm_fallback_enabled = False
        llm_polish_enabled = False
        llm_select_enabled = False
        llm_polish_lite_enabled = False

    async def fake_provider(*, timeout_sec: float = 3.0):
        _ = timeout_sec
        return {
            "ok": False,
            "configured": False,
            "url": "",
            "error": "llm provider missing",
        }

    monkeypatch.setattr("pallas.product.llm.config.get_llm_config", lambda: FakeCfg())
    monkeypatch.setattr(
        "pallas.product.llm.startup_probe.probe_llm_provider",
        fake_provider,
    )
    results = await probe_llm_service(timeout_sec=5.0)
    assert len(results) == 1
    assert results[0].ok is False
    assert results[0].error == "尚未配置 Provider"
    assert results[0].failure_class == "runtime_unavailable"


def test_normalize_llm_probe_error() -> None:
    assert normalize_llm_probe_error("Connect timeout") == "超时"
    assert normalize_llm_probe_error("ConnectError") == "连接失败"
    assert normalize_llm_probe_error("") == "不可用"


def test_llm_provider_registered() -> None:
    assert "llm" in registered_service_probe_names()
    assert "media" in registered_service_probe_names()
