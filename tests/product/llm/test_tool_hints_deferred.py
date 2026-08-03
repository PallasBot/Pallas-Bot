from __future__ import annotations

from pallas.product.llm.tools.bootstrap import reset_llm_tools_bootstrap_for_tests
from pallas.product.llm.tools.declare import llm_command_tool_row
from pallas.product.llm.tools.discovery import TOOLS_FIND_NAME, search_deferred_tools
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


def test_music_selective_catalog_excludes_unrelated_command_tools(monkeypatch) -> None:
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
                    hints=["点歌", "放首歌", "来首", "音乐"],
                )
            ),
            plugin_name="sing",
            plugin_title="唱歌",
        )
    )
    register_tool(
        build_command_tool_spec(
            parse_llm_command_tool_decl(
                llm_command_tool_row(
                    name="sing.sing",
                    command_id="sing.sing",
                    description="让牛牛翻唱指定歌曲。",
                    parameters={
                        "type": "object",
                        "properties": {"song": {"type": "string"}},
                        "required": ["song"],
                    },
                    command_template="牛牛唱歌 {song}",
                    hints=["唱歌", "唱一首", "翻唱", "来一首"],
                )
            ),
            plugin_name="sing",
            plugin_title="唱歌",
        )
    )
    register_tool(
        build_command_tool_spec(
            parse_llm_command_tool_decl(
                llm_command_tool_row(
                    name="duel.cage",
                    command_id="duel.cage",
                    description="决斗",
                    parameters={"type": "object", "properties": {}},
                    command_template="牛牛决斗",
                    hints=["决斗"],
                )
            ),
            plugin_name="duel",
            plugin_title="决斗",
        )
    )
    meta = tool_metadata_for_chat(task="llm_chat", user_text="牛牛放一首铁花飞")
    names = {item["function"]["name"] for item in meta.get("tool_schemas") or []}
    assert names == {"sing__request_song"}
    assert meta.get("selection_source") == "selective+ranked"
    assert "duel__cage" not in names
    assert "command" not in (meta.get("tool_catalog") or {}).get("selection", {}).get("inferred_domains", [])

    cover_meta = tool_metadata_for_chat(task="llm_chat", user_text="牛牛唱一首铁花飞")
    cover_names = {item["function"]["name"] for item in cover_meta.get("tool_schemas") or []}
    assert cover_names == {"sing__sing"}

    ambiguous_meta = tool_metadata_for_chat(task="llm_chat", user_text="牛牛来一首铁花飞")
    ambiguous_names = {item["function"]["name"] for item in ambiguous_meta.get("tool_schemas") or []}
    assert ambiguous_names == {"sing__request_song", "sing__sing"}


def test_normalize_keeps_command_dispatch_summary() -> None:
    from pallas.product.llm.tool_loop import summarize_tool_result
    from pallas.product.llm.tools.plugin_bootstrap import command_dispatch_result_summary
    from pallas.product.llm.tools.registry import normalize_tool_result

    summary_text = command_dispatch_result_summary("牛牛点歌 铁花飞")
    normalized = normalize_tool_result({
        "ok": True,
        "result": {
            "command_text": "牛牛点歌 铁花飞",
            "summary": summary_text,
        },
    })
    assert normalized["ok"] is True
    assert normalized["result"]["command_text"] == "牛牛点歌 铁花飞"
    summary = summarize_tool_result(normalized)
    assert summary["result_preview"]
    assert "铁花飞" in summary["result_preview"]
    assert "平凡之路" not in summary["result_preview"]
    assert "歌名/参数原文" not in summary["result_preview"]
    assert summary["result_preview"].startswith("已执行「")
    assert "极短口语" in summary["result_preview"]
    assert "系统腔" in summary["result_preview"]


def test_command_dispatch_summary_forbids_meta_templates() -> None:
    from pallas.product.llm.tools.plugin_bootstrap import command_dispatch_result_summary

    text = command_dispatch_result_summary("牛牛画画 一头牛")
    assert text.startswith("已执行「牛牛画画 一头牛」")
    assert "禁止「已派发/帮你找找/正在生成」" in text
    assert "系统腔" in text
