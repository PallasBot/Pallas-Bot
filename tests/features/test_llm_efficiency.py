from __future__ import annotations

from pallas.product.llm.chat_queue import (
    clear_chat_queue_for_tests,
    merge_queued_chat,
    queue_size_for_tests,
    stash_chat_during_cooldown,
)
from pallas.product.llm.config import LlmConfig, clear_llm_config_cache
from pallas.product.llm.reply_gate import evaluate_llm_reply_gate
from pallas.product.llm.tools import registry as tools_registry  # noqa: F401
from pallas.product.llm.tools.registry import tool_openai_schemas


def test_reply_gate_skips_face_only() -> None:
    cfg = LlmConfig(llm_reply_gate_enabled=True, llm_reply_gate_min_chars=1)
    assert evaluate_llm_reply_gate("[CQ:face,id=123]", cfg=cfg) == "skip"


def test_reply_gate_proceeds_normal_text() -> None:
    cfg = LlmConfig(llm_reply_gate_enabled=True, llm_reply_gate_min_chars=1)
    assert evaluate_llm_reply_gate("你知道谁是银灰吗", cfg=cfg) == "proceed"


def test_reply_gate_disabled_always_proceeds() -> None:
    cfg = LlmConfig(llm_reply_gate_enabled=False)
    assert evaluate_llm_reply_gate("[CQ:face,id=123]", cfg=cfg) == "proceed"


def test_chat_queue_merge_last_wins_on_cooldown() -> None:
    clear_chat_queue_for_tests()
    cfg = LlmConfig(llm_chat_queue_merge=True)
    stash_chat_during_cooldown(1, 2, 3, "第一条", cfg=cfg)
    assert queue_size_for_tests() == 1
    merged = merge_queued_chat(1, 2, 3, "第二条", cfg=cfg)
    assert merged.merged is True
    assert merged.text == "第一条\n第二条"
    assert queue_size_for_tests() == 0


def test_tools_blacklist_filters_schema(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.tools.registry.get_llm_config",
        lambda: LlmConfig(llm_tools_enabled=True, llm_tools_blacklist=["arknights.operator.get"]),
    )
    schemas = tool_openai_schemas(domains=frozenset({"arknights"}))
    names = {item["function"]["name"] for item in schemas}
    assert "arknights.operator.get" not in names
    clear_llm_config_cache()
