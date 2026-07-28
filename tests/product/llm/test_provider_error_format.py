"""LlmProviderError 展示与 probe 草稿探测。"""

from __future__ import annotations

import httpx
import pytest

from pallas.product.llm.provider_client import (
    format_provider_http_error,
    format_provider_transport_error,
    host_from_url,
)


def test_host_from_url() -> None:
    assert host_from_url("https://api.siliconflow.cn/v1/models") == "api.siliconflow.cn"
    assert host_from_url("") == ""


def test_format_provider_http_error_524() -> None:
    msg = format_provider_http_error(524, "<html>error code: 524</html>")
    assert msg.startswith("HTTP 524:")
    assert "524" in msg


def test_format_provider_http_error_empty_body() -> None:
    assert format_provider_http_error(503) == "HTTP 503"


def test_format_provider_transport_connect_timeout() -> None:
    exc = httpx.ConnectTimeout("timed out")
    msg = format_provider_transport_error(
        exc,
        url="https://api.siliconflow.cn/v1/models",
    )
    assert "连接超时" in msg
    assert "api.siliconflow.cn" in msg


def test_format_provider_transport_connect_error() -> None:
    exc = httpx.ConnectError("Connection refused")
    msg = format_provider_transport_error(exc, url="http://127.0.0.1:11434/api/tags")
    assert "连接失败" in msg
    assert "127.0.0.1" in msg


@pytest.mark.asyncio
async def test_probe_provider_accepts_draft_body(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import model_admin

    async def fake_fetch(
        provider_id: str,
        *,
        base_url: str = "",
        api_key: str = "",
        api_key_env: str = "",
        kind: str = "",
        request_method: str = "",
        cfg=None,
        timeout_sec: float = 15.0,
    ) -> dict:
        assert provider_id == "siliconflow"
        assert base_url == "https://api.siliconflow.cn/v1"
        assert api_key == "sk-draft"
        assert kind == "remote"
        return {
            "provider_id": provider_id,
            "ok": False,
            "models": [],
            "source": "openai",
            "error": "HTTP 524: error code: 524",
            "status": 524,
        }

    monkeypatch.setattr(model_admin, "fetch_provider_models", fake_fetch)
    monkeypatch.setattr(
        "pallas.product.llm.providers_store.find_provider",
        lambda _pid: None,
    )

    result = await model_admin.probe_provider(
        "siliconflow",
        base_url="https://api.siliconflow.cn/v1",
        api_key="sk-draft",
        kind="remote",
    )
    assert result["reachable"] is False
    assert result["status"] == 524
    assert "HTTP 524" in str(result["error"])


@pytest.mark.asyncio
async def test_probe_provider_missing_without_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.product.llm import model_admin

    monkeypatch.setattr(
        "pallas.product.llm.providers_store.find_provider",
        lambda _pid: None,
    )
    result = await model_admin.probe_provider("missing-id")
    assert result["reachable"] is False
    assert "不存在" in str(result["error"]) or "草稿" in str(result["error"])
