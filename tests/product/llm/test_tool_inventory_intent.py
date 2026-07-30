"""盘点意图：查询通道 overlay。"""

from __future__ import annotations

from pallas.product.llm.tools.bootstrap import reset_llm_tools_bootstrap_for_tests
from pallas.product.llm.tools.contracts import ToolCapability
from pallas.product.llm.tools.declare import llm_command_tool_row
from pallas.product.llm.tools.discovery import TOOLS_FIND_NAME, register_discovery_tools
from pallas.product.llm.tools.inventory import is_inventory_intent, is_query_tool
from pallas.product.llm.tools.metadata import parse_llm_command_tool_decl
from pallas.product.llm.tools.plugin_bootstrap import build_command_tool_spec
from pallas.product.llm.tools.registry import (
    LlmToolSource,
    LlmToolSpec,
    clear_tool_registry,
    register_tool,
    tool_catalog_for_chat,
    tool_metadata_for_chat,
)


def _cfg(**overrides):
    base = {
        "llm_tools_enabled": True,
        "llm_tools_selective": True,
        "llm_tools_soft_recall_enabled": True,
        "llm_tools_soft_recall_min_score": 6,
        "llm_tools_soft_recall_max_candidates": 3,
        "llm_tools_blacklist": [],
        "llm_tools_desc_max_len": 200,
    }
    base.update(overrides)
    return type("Cfg", (), base)()


def test_is_inventory_intent_phrases() -> None:
    assert is_inventory_intent("都会啥表情")
    assert is_inventory_intent("有哪些表情")
    assert is_inventory_intent("你会啥")
    assert is_inventory_intent("有啥功能")
    assert is_inventory_intent("功能列表")
    assert is_inventory_intent("有没有举牌之类的表情")
    assert is_inventory_intent("有没有表情")
    assert not is_inventory_intent("做个摸表情")
    assert not is_inventory_intent("放首歌")
    assert not is_inventory_intent("会")  # 过宽单字不命中
    assert not is_inventory_intent("")


def test_is_query_tool_by_capability_and_name() -> None:
    read_only = LlmToolSpec(
        name="demo.ping",
        description="ping",
        parameters={"type": "object", "properties": {}},
        domains=frozenset({"demo"}),
        handler=lambda args, ctx=None: {"ok": True},
        capabilities=frozenset({ToolCapability.READ_ONLY.value}),
    )
    assert is_query_tool(read_only)

    list_tool = LlmToolSpec(
        name="memes.list",
        description="列表",
        parameters={"type": "object", "properties": {}},
        domains=frozenset({"memes"}),
        handler=lambda args, ctx=None: {"ok": True},
        capabilities=frozenset({ToolCapability.SIDE_EFFECTING.value}),
    )
    assert is_query_tool(list_tool)

    recommend = LlmToolSpec(
        name="memes.recommend",
        description="推荐",
        parameters={"type": "object", "properties": {}},
        domains=frozenset({"memes"}),
        handler=lambda args, ctx=None: {"ok": True},
        capabilities=frozenset({ToolCapability.SIDE_EFFECTING.value}),
    )
    assert not is_query_tool(recommend)

    find_spec = LlmToolSpec(
        name=TOOLS_FIND_NAME,
        description="find",
        parameters={"type": "object", "properties": {}},
        domains=frozenset({"tools"}),
        handler=lambda args, ctx=None: {"ok": True},
        source=LlmToolSource.BUILTIN,
        capabilities=frozenset({ToolCapability.READ_ONLY.value}),
    )
    assert is_query_tool(find_spec)


def _register_memes_and_find() -> None:
    clear_tool_registry()
    register_discovery_tools()
    register_tool(
        build_command_tool_spec(
            parse_llm_command_tool_decl(
                llm_command_tool_row(
                    name="memes.list",
                    command_id="memes.list",
                    description="查看可用表情模板列表。只列名称，不制作图片。",
                    parameters={"type": "object", "properties": {}},
                    command_template="牛牛表情列表",
                    hints=["表情列表", "有哪些表情", "表情模板"],
                    visibility="deferred",
                    source_segments="none",
                )
            ),
            plugin_name="memes",
            plugin_title="表情",
        )
    )
    register_tool(
        build_command_tool_spec(
            parse_llm_command_tool_decl(
                llm_command_tool_row(
                    name="memes.recommend",
                    command_id="memes.recommend",
                    description="按意图推荐并制作表情包",
                    parameters={
                        "type": "object",
                        "properties": {"intent": {"type": "string"}},
                        "required": ["intent"],
                    },
                    command_template="牛牛表情推荐 {intent}",
                    hints=["做表情", "做个表情", "表情包", "meme"],
                    source_segments="media",
                )
            ),
            plugin_name="memes",
            plugin_title="表情",
        )
    )


def test_inventory_opens_find_and_deferred_list(monkeypatch) -> None:
    reset_llm_tools_bootstrap_for_tests()
    monkeypatch.setattr("pallas.product.llm.tools.registry.get_llm_config", lambda: _cfg())
    monkeypatch.setattr(
        "pallas.product.llm.tools.registry.get_arknights_kb_config",
        lambda: type("Kb", (), {"arknights_kb_enabled": True})(),
    )
    _register_memes_and_find()

    catalog = tool_catalog_for_chat(task="llm_chat", user_text="都会啥表情")
    assert catalog is not None
    assert catalog.selection.inventory_intent is True
    names = {item.name for item in catalog.tools}
    assert TOOLS_FIND_NAME in names
    assert "memes.list" in names
    assert "memes.recommend" not in names

    meta = tool_metadata_for_chat(task="llm_chat", user_text="都会啥表情")
    assert meta.get("tool_choice_prefer") == "required"
    assert meta.get("inventory_intent") is True


def test_inventory_ask_has_meme_excludes_recommend(monkeypatch) -> None:
    reset_llm_tools_bootstrap_for_tests()
    monkeypatch.setattr("pallas.product.llm.tools.registry.get_llm_config", lambda: _cfg())
    monkeypatch.setattr(
        "pallas.product.llm.tools.registry.get_arknights_kb_config",
        lambda: type("Kb", (), {"arknights_kb_enabled": True})(),
    )
    _register_memes_and_find()

    catalog = tool_catalog_for_chat(task="llm_chat", user_text="有没有举牌之类的表情")
    assert catalog is not None
    assert catalog.selection.inventory_intent is True
    names = {item.name for item in catalog.tools}
    assert "memes.recommend" not in names
    assert "memes.list" in names or TOOLS_FIND_NAME in names


def test_make_meme_does_not_force_inventory_list(monkeypatch) -> None:
    reset_llm_tools_bootstrap_for_tests()
    monkeypatch.setattr("pallas.product.llm.tools.registry.get_llm_config", lambda: _cfg())
    monkeypatch.setattr(
        "pallas.product.llm.tools.registry.get_arknights_kb_config",
        lambda: type("Kb", (), {"arknights_kb_enabled": True})(),
    )
    _register_memes_and_find()

    catalog = tool_catalog_for_chat(task="llm_chat", user_text="做个摸表情")
    assert catalog is not None
    assert catalog.selection.inventory_intent is False
    names = {item.name for item in catalog.tools}
    assert "memes.list" not in names
    assert "memes.recommend" in names


def test_inventory_without_hard_domain_includes_find(monkeypatch) -> None:
    reset_llm_tools_bootstrap_for_tests()
    monkeypatch.setattr("pallas.product.llm.tools.registry.get_llm_config", lambda: _cfg())
    monkeypatch.setattr(
        "pallas.product.llm.tools.registry.get_arknights_kb_config",
        lambda: type("Kb", (), {"arknights_kb_enabled": True})(),
    )
    clear_tool_registry()
    register_discovery_tools()

    catalog = tool_catalog_for_chat(task="llm_chat", user_text="你都会啥")
    assert catalog is not None
    assert catalog.selection.inventory_intent is True
    names = {item.name for item in catalog.tools}
    assert TOOLS_FIND_NAME in names


def test_build_command_tool_marks_list_read_only() -> None:
    spec = build_command_tool_spec(
        parse_llm_command_tool_decl(
            llm_command_tool_row(
                name="memes.list",
                command_id="memes.list",
                description="列表",
                parameters={"type": "object", "properties": {}},
                command_template="牛牛表情列表",
            )
        ),
        plugin_name="memes",
        plugin_title="表情",
    )
    assert ToolCapability.READ_ONLY.value in spec.capabilities
    assert ToolCapability.SIDE_EFFECTING.value not in spec.capabilities


def test_declared_capabilities_override_name_heuristic() -> None:
    spec = build_command_tool_spec(
        parse_llm_command_tool_decl(
            llm_command_tool_row(
                name="help.show",
                command_id="help.help",
                description="帮助总览",
                parameters={"type": "object", "properties": {}},
                command_template="牛牛帮助",
                capabilities=["read_only"],
            )
        ),
        plugin_name="help",
        plugin_title="帮助",
    )
    assert ToolCapability.READ_ONLY.value in spec.capabilities
    assert ToolCapability.SIDE_EFFECTING.value not in spec.capabilities
    assert ToolCapability.REQUIRES_GROUP_CONTEXT.value in spec.capabilities


def test_inventory_hit_metric(monkeypatch) -> None:
    from pallas.product.llm.task_metrics import clear_llm_task_metrics_for_tests, llm_task_metrics_snapshot

    reset_llm_tools_bootstrap_for_tests()
    clear_llm_task_metrics_for_tests()
    monkeypatch.setattr("pallas.product.llm.tools.registry.get_llm_config", lambda: _cfg())
    monkeypatch.setattr(
        "pallas.product.llm.tools.registry.get_arknights_kb_config",
        lambda: type("Kb", (), {"arknights_kb_enabled": True})(),
    )
    clear_tool_registry()
    register_discovery_tools()
    tool_metadata_for_chat(task="llm_chat", user_text="你都会啥")
    snap = llm_task_metrics_snapshot()
    assert snap["by_task"]["llm_chat"]["inventory_hit"] == 1
