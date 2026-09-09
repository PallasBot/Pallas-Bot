from __future__ import annotations


def test_external_llm_tool_survives_bootstrap_refresh() -> None:
    from pallas.product.llm.tools import external
    from pallas.product.llm.tools.bootstrap import ensure_llm_tools_bootstrapped
    from pallas.product.llm.tools.registry import clear_tool_registry, list_registered_tools

    name = "test.external.read"

    async def handler(_args, _ctx):
        return {"ok": True, "value": 1}

    external.clear_external_llm_tools_for_tests()
    clear_tool_registry()
    try:
        external.register_external_llm_tool(
            name=name,
            description="测试外部只读工具",
            parameters={"type": "object", "properties": {}},
            domains={"test"},
            handler=handler,
            plugin_name="test_plugin",
            capabilities={"read_only"},
        )
        ensure_llm_tools_bootstrapped(force=True)
        tool = next(item for item in list_registered_tools() if item.name == name)
        assert tool.plugin_name == "test_plugin"
        assert tool.read_only is True
    finally:
        external.clear_external_llm_tools_for_tests()
        clear_tool_registry()
