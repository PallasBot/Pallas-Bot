from __future__ import annotations

from types import SimpleNamespace

import pytest

from pallas.product.llm.tools import registry
from pallas.product.llm.tools.contracts import (
    ToolAuditInfo,
    ToolCapability,
    ToolCatalogEntry,
    ToolCatalogSelection,
    ToolCatalogSnapshot,
    ToolResultEnvelope,
)


@pytest.fixture(autouse=True)
def restore_global_tool_registry() -> None:
    yield
    from pallas.product.llm.tools.bootstrap import ensure_llm_tools_bootstrapped, reset_llm_tools_bootstrap_for_tests

    reset_llm_tools_bootstrap_for_tests()
    ensure_llm_tools_bootstrapped()


def test_tool_catalog_snapshot_roundtrip() -> None:
    snap = ToolCatalogSnapshot(
        tools=[
            ToolCatalogEntry(
                name="arknights.operator.get",
                description="查询干员",
                parameters={"type": "object", "properties": {"name": {"type": "string"}}},
                source="builtin",
                domains=["arknights"],
                capabilities=["read_only"],
            )
        ],
        selection=ToolCatalogSelection(tools_enabled=True, schema_count=1, inferred_domains=["arknights"]),
    )
    payload = snap.model_dump(mode="json")
    restored = ToolCatalogSnapshot.model_validate(payload)
    assert restored.tools[0].name == "arknights.operator.get"
    assert restored.version == "tool_catalog/v1"


def test_tool_result_envelope_roundtrip() -> None:
    envelope = ToolResultEnvelope(
        ok=True,
        result={"found": True},
        source="builtin",
        audit=ToolAuditInfo(command_id="cmd.roll", mcp_server_id="notion"),
    )
    payload = envelope.model_dump(mode="json")
    restored = ToolResultEnvelope.model_validate(payload)
    assert restored.ok is True
    assert restored.result == {"found": True}
    assert restored.audit.command_id == "cmd.roll"
    assert restored.audit.mcp_server_id == "notion"


def test_tool_catalog_entry_from_spec(monkeypatch) -> None:
    monkeypatch.setattr(registry, "ensure_tools_loaded", lambda: None)

    async def handler(args, _ctx):
        return {"ok": True}

    spec = registry.LlmToolSpec(
        name="plugin.echo",
        description="echo",
        parameters={"type": "object", "properties": {}},
        domains=frozenset({"command", "demo"}),
        handler=handler,
        source=registry.LlmToolSource.PLUGIN_COMMAND,
        command_id="demo.echo",
        plugin_name="demo",
        capabilities=frozenset({ToolCapability.SIDE_EFFECTING.value}),
    )
    entry = registry.tool_catalog_entry_from_spec(spec)
    assert entry.name == "plugin.echo"
    assert entry.source == "plugin_command"
    assert entry.audit.plugin_name == "demo"
    assert "side_effecting" in entry.capabilities


def test_tool_catalog_entry_from_mcp_spec(monkeypatch) -> None:
    monkeypatch.setattr(registry, "ensure_tools_loaded", lambda: None)

    spec = registry.LlmToolSpec(
        name="mcp.notion.search",
        description="notion search",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        domains=frozenset({"mcp", "notion"}),
        handler=lambda *_args, **_kwargs: {"ok": False},
        source=registry.LlmToolSource.MCP,
        provider_name="mcp",
        mcp_server_id="notion",
        capabilities=frozenset({ToolCapability.READ_ONLY.value}),
    )

    entry = registry.tool_catalog_entry_from_spec(spec)

    assert entry.source == "mcp"
    assert entry.audit.mcp_server_id == "notion"
    assert entry.capabilities == ["read_only"]


def test_tool_metadata_for_chat_includes_tool_catalog(monkeypatch) -> None:
    monkeypatch.setattr(registry, "ensure_tools_loaded", lambda: None)
    monkeypatch.setattr(
        registry,
        "get_llm_config",
        lambda: SimpleNamespace(
            llm_tools_enabled=True,
            llm_tools_blacklist=[],
            llm_tools_desc_max_len=120,
            llm_tools_selective=False,
        ),
    )
    monkeypatch.setattr(
        registry,
        "get_arknights_kb_config",
        lambda: SimpleNamespace(arknights_kb_enabled=True),
    )
    monkeypatch.setattr(registry, "load_tool_description_overrides", dict)
    registry.clear_tool_registry()

    async def handler(args, _ctx):
        return {"ok": True}

    registry.register_tool(
        registry.LlmToolSpec(
            name="test.echo",
            description="echo tool",
            parameters={"type": "object", "properties": {}},
            domains=frozenset({"test"}),
            handler=handler,
        )
    )

    meta = registry.tool_metadata_for_chat(task="llm_chat", user_text="查一下银灰")
    assert meta.get("tools_enabled") is True
    assert isinstance(meta.get("tool_catalog"), dict)
    assert meta["tool_catalog"]["version"] == "tool_catalog/v1"
    assert isinstance(meta.get("tool_schemas"), list)
    assert meta["tool_schema_count"] == len(meta["tool_schemas"])


def test_register_mcp_tools(monkeypatch) -> None:
    from pallas.product.llm.config import LlmMcpServerConfig
    from pallas.product.llm.tools.mcp_bootstrap import clear_mcp_tools, register_mcp_tools

    registry.clear_tool_registry()
    clear_mcp_tools()
    server = LlmMcpServerConfig(id="notion", transport="stdio", command=["python", "-m", "fake"])
    monkeypatch.setattr(
        "pallas.product.llm.tools.mcp_bootstrap.get_llm_config",
        lambda: SimpleNamespace(mcp_servers=[server]),
    )
    monkeypatch.setattr(
        "pallas.product.llm.tools.mcp_bootstrap.list_mcp_tools",
        lambda _server: [
            {
                "name": "search",
                "description": "Search Notion",
                "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
                "annotations": {"readOnlyHint": True},
            }
        ],
    )

    assert register_mcp_tools() == 1
    spec = registry.list_registered_tools()[0]
    assert spec.name == "mcp.notion.search"
    assert spec.source == registry.LlmToolSource.MCP
    assert spec.mcp_server_id == "notion"
    assert ToolCapability.READ_ONLY.value in spec.capabilities


@pytest.mark.asyncio
async def test_execute_tool_async_runs_mcp_branch(monkeypatch) -> None:
    monkeypatch.setattr(registry, "ensure_tools_loaded", lambda: None)
    registry.clear_tool_registry()

    registry.register_tool(
        registry.LlmToolSpec(
            name="mcp.notion.search",
            description="Search Notion",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            domains=frozenset({"mcp", "notion"}),
            handler=lambda *_args, **_kwargs: {"ok": False, "error": "should not run"},
            source=registry.LlmToolSource.MCP,
            provider_name="mcp",
            mcp_server_id="notion",
            capabilities=frozenset({ToolCapability.READ_ONLY.value}),
        )
    )

    async def fake_execute(spec, arguments):
        assert spec.name == "mcp.notion.search"
        assert arguments == {"query": "amiya"}
        return {
            "ok": True,
            "result": {"structured_content": {"hits": 1}},
        }

    monkeypatch.setattr("pallas.product.llm.tools.mcp_bootstrap.execute_mcp_tool_async", fake_execute)

    result = await registry.execute_tool_async("mcp.notion.search", {"query": "amiya"}, context=None)

    assert result["ok"] is True
    assert result["source"] == "mcp"
    assert result["audit"]["mcp_server_id"] == "notion"
    assert result["result"] == {"structured_content": {"hits": 1}}
