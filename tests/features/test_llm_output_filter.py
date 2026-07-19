from __future__ import annotations

from pallas.core.platform.ai_callback.task_types import (
    LLM_CHAT_TASK_TYPE,
    REPEATER_POLISH_LITE_TASK_TYPE,
)
from pallas.product.llm.config import LlmConfig
from pallas.product.llm.output_filter import (
    CHAT_HARD_BLOCK_PHRASES,
    match_output_filter,
    output_filter_enabled,
    resolve_output_filtered_reply,
)


def test_match_output_filter_chat_hard_block_celebration_template(monkeypatch) -> None:
    from pallas.product.llm.config import LlmConfig

    monkeypatch.setattr(
        "pallas.product.llm.config.get_llm_config",
        lambda: LlmConfig(llm_output_filter_chat_hard_phrases=list(CHAT_HARD_BLOCK_PHRASES)),
    )
    hit = match_output_filter("晚安！希望每个庆典都能顺利举行", "chat")
    assert hit is not None
    assert hit.tier == "hard_block"
    assert hit.phrase == "希望每个庆典"


def test_match_output_filter_chat_hard_block() -> None:
    hit = match_output_filter("博士您好，想聊点什么？", "chat")
    assert hit is not None
    assert hit.tier == "hard_block"
    assert hit.phrase == "博士"


def test_match_output_filter_chat_soft_retry() -> None:
    hit = match_output_filter("今天很高兴见到你", "chat")
    assert hit is not None
    assert hit.tier == "soft_retry"
    assert hit.phrase == "很高兴"


def test_match_output_filter_polish_lite_merges_tiers() -> None:
    hit = match_output_filter("那就继续聊吧", "polish_lite")
    assert hit is not None
    assert hit.tier == "hard_block"


def test_resolve_output_filtered_reply_uses_fallback() -> None:
    task = {
        "task_type": REPEATER_POLISH_LITE_TASK_TYPE,
        "fallback_text": "好耶",
    }
    assert resolve_output_filtered_reply(task, "要不要继续聊？") == "好耶"


def test_resolve_output_filtered_reply_silent_without_fallback() -> None:
    task = {"task_type": LLM_CHAT_TASK_TYPE}
    assert resolve_output_filtered_reply(task, "博士在吗？") == ""


def test_resolve_output_filtered_reply_allows_clean_text() -> None:
    task = {"task_type": LLM_CHAT_TASK_TYPE}
    assert resolve_output_filtered_reply(task, "在的，咋了") == "在的，咋了"


def test_output_filter_enabled_defaults_true(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.config.get_llm_config",
        lambda: LlmConfig(llm_output_filter_enabled=True),
    )
    assert output_filter_enabled() is True


def test_output_filter_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.config.get_llm_config",
        lambda: LlmConfig(llm_output_filter_enabled=False),
    )
    task = {"task_type": LLM_CHAT_TASK_TYPE}
    assert resolve_output_filtered_reply(task, "博士在吗？") == "博士在吗？"


def test_match_output_filter_uses_configured_phrases(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.config.get_llm_config",
        lambda: LlmConfig(llm_output_filter_chat_hard_phrases=["测试词"]),
    )
    hit = match_output_filter("这里有测试词", "chat")
    assert hit is not None
    assert hit.phrase == "测试词"


def test_chat_hard_block_phrases_non_empty() -> None:
    assert "博士" in CHAT_HARD_BLOCK_PHRASES


def test_resolve_output_filtered_reply_blocks_attack_or_plugin_reply() -> None:
    task = {"task_type": LLM_CHAT_TASK_TYPE}
    assert resolve_output_filtered_reply(task, "我操你妈。群里最近有啥新鲜事儿吗？") == ""
    assert resolve_output_filtered_reply(task, "匹配失败，积分不足18点") == ""
