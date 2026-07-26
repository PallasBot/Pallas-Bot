from __future__ import annotations

from pallas.product.llm.tools.discovery import TOOLS_FIND_NAME, search_deferred_tools

from pallas.product.llm.tools.bootstrap import reset_llm_tools_bootstrap_for_tests
from pallas.product.llm.tools.declare import llm_command_tool_row
from pallas.product.llm.tools.metadata import parse_llm_command_tool_decl
from pallas.product.llm.tools.plugin_bootstrap import build_command_tool_spec
from pallas.product.llm.tools.registry import (
    clear_tool_registry,
    filter_specs_for_chat_visibility,
    register_tool,
    tool_catalog_for_chat,
    tool_metadata_for_chat,
)


def test_deferred_tool_excluded_until_hint_or_activate(monkeypatch) -> None:
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
    visible = build_command_tool_spec(
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
                hints=["点歌", "音乐"],
            )
        ),
        plugin_name="sing",
        plugin_title="唱歌",
    )
    deferred = build_command_tool_spec(
        parse_llm_command_tool_decl(
            llm_command_tool_row(
                name="sing.deep_cut",
                command_id="sing.deep_cut",
                description="冷门点歌扩展",
                parameters={"type": "object", "properties": {}},
                command_template="牛牛点歌 随机",
                hints=["冷门歌单"],
                visibility="deferred",
            )
        ),
        plugin_name="sing",
        plugin_title="唱歌",
    )
    register_tool(visible)
    register_tool(deferred)

    meta = tool_metadata_for_chat(task="llm_chat", user_text="牛牛音乐 晴天")
    names = {item["function"]["name"] for item in meta.get("tool_schemas") or []}
    assert "sing__request_song" in names
    assert "sing__deep_cut" not in names

    catalog = tool_catalog_for_chat(
        task="llm_chat",
        user_text="来点冷门歌单",
        activated_names=frozenset(),
    )
    assert catalog is not None
    catalog_names = {item.name for item in catalog.tools}
    assert "sing.deep_cut" in catalog_names

    filtered = filter_specs_for_chat_visibility(
        (visible, deferred),
        user_text="随便聊聊",
        activated_names=frozenset({"sing.deep_cut"}),
    )
    assert {spec.name for spec in filtered} == {"sing.request_song", "sing.deep_cut"}


def test_search_deferred_tools_by_query() -> None:
    reset_llm_tools_bootstrap_for_tests()
    clear_tool_registry()
    register_tool(
        build_command_tool_spec(
            parse_llm_command_tool_decl(
                llm_command_tool_row(
                    name="interact.thumb",
                    command_id="interact.thumb",
                    description="给用户点赞",
                    parameters={"type": "object", "properties": {}},
                    command_template="赞我",
                    hints=["赞我", "点赞"],
                    visibility="deferred",
                )
            ),
            plugin_name="interact",
            plugin_title="互动",
        )
    )
    matches = search_deferred_tools("点赞")
    assert matches
    assert matches[0]["name"] == "interact.thumb"
    assert TOOLS_FIND_NAME
