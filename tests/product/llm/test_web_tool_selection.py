"""联网意图应进入 selective / 强制调工具，避免口头装作搜过。"""

from __future__ import annotations

from pallas.product.llm.tools.bootstrap import reset_llm_tools_bootstrap_for_tests
from pallas.product.llm.tools.registry import clear_tool_registry, tool_catalog_for_chat, tool_metadata_for_chat
from pallas.product.llm.tools.select import infer_tool_domains
from pallas.product.llm.tools.web import register_web_tools


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


def test_search_utterance_infers_web_domain_and_requires_tool(monkeypatch) -> None:
    reset_llm_tools_bootstrap_for_tests()
    monkeypatch.setattr("pallas.product.llm.tools.registry.get_llm_config", lambda: _cfg())
    monkeypatch.setattr(
        "pallas.product.llm.tools.registry.get_arknights_kb_config",
        lambda: type("Kb", (), {"arknights_kb_enabled": True})(),
    )
    clear_tool_registry()
    register_web_tools()

    text = "帮我搜一下 Pallas-Bot"
    assert "web" in infer_tool_domains(text)
    catalog = tool_catalog_for_chat(task="llm_chat", user_text=text)
    assert catalog is not None
    assert catalog.selection.selection_source == "selective"
    assert {item.name for item in catalog.tools} >= {"web.search"}

    meta = tool_metadata_for_chat(task="llm_chat", user_text=text)
    assert meta.get("tools_enabled") is True
    assert meta.get("tool_choice_prefer") == "required"
    names = {item["function"]["name"] for item in meta["tool_schemas"]}
    assert "web__search" in names
