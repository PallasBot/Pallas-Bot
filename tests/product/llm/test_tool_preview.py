from __future__ import annotations

from pallas.product.llm.tools.bootstrap import reset_llm_tools_bootstrap_for_tests
from pallas.product.llm.tools.declare import llm_command_tool_row
from pallas.product.llm.tools.discovery import search_tools
from pallas.product.llm.tools.metadata import parse_llm_command_tool_decl
from pallas.product.llm.tools.plugin_bootstrap import build_command_tool_spec
from pallas.product.llm.tools.preview import preview_tool_intent
from pallas.product.llm.tools.registry import clear_tool_registry, register_tool


def test_preview_tool_intent_structure_sing(monkeypatch) -> None:
    reset_llm_tools_bootstrap_for_tests()
    monkeypatch.setattr(
        "pallas.product.llm.tools.registry.get_llm_config",
        lambda: type(
            "Cfg",
            (),
            {
                "llm_tools_enabled": True,
                "llm_tools_selective": True,
                "llm_tools_blacklist": [],
                "llm_tools_desc_max_len": 200,
            },
        )(),
    )
    monkeypatch.setattr(
        "pallas.product.llm.tools.registry.get_arknights_kb_config",
        lambda: type("Kb", (), {"arknights_kb_enabled": True})(),
    )
    clear_tool_registry()
    register_tool(
        build_command_tool_spec(
            parse_llm_command_tool_decl(
                llm_command_tool_row(
                    name="sing.request_song",
                    command_id="sing.request_song",
                    description="点歌",
                    parameters={
                        "type": "object",
                        "properties": {"song": {"type": "string"}},
                        "required": ["song"],
                    },
                    command_template="牛牛点歌 {song}",
                    hints=["点歌"],
                )
            ),
            plugin_name="sing",
            plugin_title="唱歌",
        )
    )
    preview = preview_tool_intent("放首铁花飞")
    assert "sing" in preview["domains"]
    assert "sing" in preview["structure_domains"]
    assert "sing.request_song" in preview["schema_tools"]


def test_search_tools_all_scope_includes_visible() -> None:
    reset_llm_tools_bootstrap_for_tests()
    clear_tool_registry()
    register_tool(
        build_command_tool_spec(
            parse_llm_command_tool_decl(
                llm_command_tool_row(
                    name="draw.image",
                    command_id="draw.draw",
                    description="画画",
                    parameters={"type": "object", "properties": {}},
                    command_template="牛牛画画 测试",
                    hints=["画画", "来张图"],
                )
            ),
            plugin_name="draw",
            plugin_title="画画",
        )
    )
    deferred_only = search_tools("画画", visibility="deferred")
    assert deferred_only == []
    all_hits = search_tools("画画", visibility=None)
    assert all_hits
    assert all_hits[0]["name"] == "draw.image"
