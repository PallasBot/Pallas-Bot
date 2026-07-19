from __future__ import annotations

import pytest

from pallas.product.llm.config import LlmMcpServerConfig
from pallas.product.llm.tools import mcp_bootstrap


def test_mcp_http_blocked_without_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.repo_env_raw_value",
        lambda _key: "",
    )
    server = LlmMcpServerConfig(id="demo", transport="http", url="http://127.0.0.1:8765/mcp")
    with pytest.raises(RuntimeError, match="LLM_MCP_HTTP_ALLOWLIST"):
        mcp_bootstrap._call_mcp_http(server, method="tools/list")


def test_mcp_http_allowed_with_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.repo_env_raw_value",
        lambda key: "http://127.0.0.1:8765" if key == "LLM_MCP_HTTP_ALLOWLIST" else "",
    )
    assert mcp_bootstrap._mcp_http_allowed("http://127.0.0.1:8765/mcp") is True
    assert mcp_bootstrap._mcp_http_allowed("http://evil.example/mcp") is False
