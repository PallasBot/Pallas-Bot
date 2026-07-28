"""MCP 配置经 WebUI llm section 落盘与重注册。"""

from __future__ import annotations

from types import SimpleNamespace


def test_llm_webui_config_exposes_mcp_fields(monkeypatch) -> None:
    from pallas.product.llm import webui_config as webui_mod
    from pallas.product.llm.config import LlmConfig, LlmMcpServerConfig

    monkeypatch.setattr(
        webui_mod,
        "get_llm_config",
        lambda: LlmConfig(
            mcp_servers=[
                LlmMcpServerConfig(id="prts", transport="stdio", command=["uvx", "prts-mcp"]),
            ]
        ),
    )
    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.repo_env_raw_value",
        lambda key: "http://127.0.0.1:8765" if key == "LLM_MCP_HTTP_ALLOWLIST" else None,
    )
    cfg = webui_mod.get_llm_webui_config()
    assert len(cfg.mcp_servers) == 1
    assert cfg.mcp_servers[0].id == "prts"
    assert cfg.llm_mcp_http_allowlist == "http://127.0.0.1:8765"


def test_llm_section_maps_mcp_env_keys() -> None:
    from pallas.console.webui.env_sections import clear_webui_env_sections_cache, get_webui_env_section

    clear_webui_env_sections_cache()
    section = get_webui_env_section("llm")
    assert section.field_to_env["mcp_servers"] == "LLM_MCP_SERVERS"
    assert section.field_to_env["llm_mcp_http_allowlist"] == "LLM_MCP_HTTP_ALLOWLIST"


def test_apply_llm_mcp_patch_rewrites_env_and_reboots_tools(monkeypatch) -> None:
    from pallas.console.webui import apply_webui_env_section_patch
    from pallas.console.webui.env_sections import clear_webui_env_sections_cache
    from pallas.product.llm import webui_config as webui_mod
    from pallas.product.llm.config import LlmConfig

    clear_webui_env_sections_cache()
    monkeypatch.setattr(webui_mod, "get_llm_config", lambda: LlmConfig())
    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.repo_env_raw_value",
        lambda _key: None,
    )

    written: dict[str, str] = {}
    reboot: list[bool] = []

    monkeypatch.setattr(
        "pallas.console.webui.env_sections.upsert_repo_settings_items",
        lambda items: written.update(items),
    )
    monkeypatch.setattr(
        "pallas.product.llm.config.clear_llm_config_cache",
        lambda: None,
    )
    monkeypatch.setattr(
        "pallas.product.llm.tools.bootstrap.ensure_llm_tools_bootstrapped",
        lambda *, force=False: reboot.append(force),
    )
    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.purge_misplaced_ai_env_keys_from_webui",
        lambda: None,
    )

    apply_webui_env_section_patch(
        "llm",
        {
            "mcp_servers": [
                {
                    "id": "demo",
                    "transport": "stdio",
                    "command": ["echo", "hi"],
                    "enabled_tools": ["a"],
                    "url": "",
                }
            ],
            "llm_mcp_http_allowlist": "http://127.0.0.1:9",
        },
    )

    assert "LLM_MCP_SERVERS" in written
    assert '"id": "demo"' in written["LLM_MCP_SERVERS"] or '"id":"demo"' in written["LLM_MCP_SERVERS"]
    assert written["LLM_MCP_HTTP_ALLOWLIST"] == "http://127.0.0.1:9"
    assert reboot == [True]


def test_mcp_registration_snapshot_records_errors(monkeypatch) -> None:
    from pallas.product.llm.tools import mcp_bootstrap
    from pallas.product.llm.tools.bootstrap import reset_llm_tools_bootstrap_for_tests
    from pallas.product.llm.tools.registry import clear_tool_registry

    reset_llm_tools_bootstrap_for_tests()
    clear_tool_registry()
    mcp_bootstrap.clear_mcp_tools()

    server = SimpleNamespace(
        id="broken",
        transport="stdio",
        command=["false"],
        enabled_tools=[],
        url="",
    )
    monkeypatch.setattr(
        mcp_bootstrap,
        "get_llm_config",
        lambda: SimpleNamespace(mcp_servers=[server]),
    )
    monkeypatch.setattr(
        mcp_bootstrap,
        "list_mcp_tools",
        lambda _server: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    count = mcp_bootstrap.register_mcp_tools()
    snap = mcp_bootstrap.mcp_registration_snapshot()
    assert count == 0
    assert snap["errors"] == [{"server_id": "broken", "error": "boom"}]
    assert snap["registered_count"] == 0
