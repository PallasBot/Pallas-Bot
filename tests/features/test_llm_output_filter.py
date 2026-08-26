from __future__ import annotations

from pallas.core.platform.ai_callback.task_types import LLM_CHAT_TASK_TYPE
from pallas.product.llm.config import LlmConfig
from pallas.product.llm.output_filter import (
    CHAT_HARD_BLOCK_PHRASES,
    _press_reply_to_limit,
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


def test_resolve_output_filtered_reply_silent_without_fallback() -> None:
    task = {"task_type": LLM_CHAT_TASK_TYPE}
    assert resolve_output_filtered_reply(task, "博士在吗？") == ""


def test_resolve_output_filtered_reply_allows_clean_text() -> None:
    task = {"task_type": LLM_CHAT_TASK_TYPE}
    assert resolve_output_filtered_reply(task, "在的，咋了") == "在的，咋了"


def test_resolve_output_filtered_reply_preserves_single_character_confirmation() -> None:
    task = {"task_type": LLM_CHAT_TASK_TYPE}
    assert resolve_output_filtered_reply(task, "在。") == "在。"


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


def test_resolve_output_filtered_reply_pass_is_silent() -> None:
    task = {"task_type": LLM_CHAT_TASK_TYPE}
    assert resolve_output_filtered_reply(task, '{"reply":"PASS"}') == ""
    assert resolve_output_filtered_reply(task, "PASS") == ""


def test_resolve_output_filtered_reply_extracts_json_reply() -> None:
    task = {"task_type": LLM_CHAT_TASK_TYPE}
    assert resolve_output_filtered_reply(task, '{"reply":"在的，咋了","intent":"chat"}') == "在的，咋了"


def test_resolve_output_filtered_reply_drops_token_leak() -> None:
    task = {"task_type": LLM_CHAT_TASK_TYPE}
    assert resolve_output_filtered_reply(task, "你好 <thinking>x</thinking>") == ""


def test_resolve_output_filtered_reply_blocks_filler_and_soft_refuse() -> None:
    task = {"task_type": LLM_CHAT_TASK_TYPE}
    assert resolve_output_filtered_reply(task, "还行吧") == ""
    assert resolve_output_filtered_reply(task, "哞~ 别这么说嘛，我们还是好朋友呢。还行吧。") == ""
    assert resolve_output_filtered_reply(task, "哈哈 Jest~") == ""
    # 口语里带「还行吧」但非整句垫词：允许
    assert resolve_output_filtered_reply(task, "谢谢，还行吧") == "谢谢，还行吧"


def test_resolve_output_filtered_reply_strips_orphan_leading_particle() -> None:
    task = {"task_type": LLM_CHAT_TASK_TYPE}
    assert resolve_output_filtered_reply(task, "吧。深目的确是个特色。") == "深目的确是个特色。"


def test_resolve_output_filtered_reply_blocks_service_tone_after_strip() -> None:
    task = {"task_type": LLM_CHAT_TASK_TYPE}
    assert resolve_output_filtered_reply(task, "吧。时间管理真的很重要呢。你有没有什么好方法来提高效率？") == ""
    assert resolve_output_filtered_reply(task, "得看设定啦。") == ""


def test_resolve_output_filtered_reply_enforces_max_length() -> None:
    task = {
        "task_type": LLM_CHAT_TASK_TYPE,
        "reply_max_length": 20,
        "fallback_text": "行",
    }
    long = "听说你对科目录得挺全的，我这记性就没那么好啦。对了，你喜欢哪种动物啊？"
    assert resolve_output_filtered_reply(task, long) == "行"


def test_press_reply_to_limit_truncates_at_sentence_ending() -> None:
    pressed = _press_reply_to_limit("哎，今天真是累死了。明天还要早起呢。", max_len=12)
    assert len(pressed) <= 12
    assert pressed.endswith("。")


def test_press_reply_to_limit_keeps_single_bubble_when_no_clean_cut() -> None:
    text = "这个参数的中文名确实念起来有点长，你仔细读两遍可能就顺了"
    assert _press_reply_to_limit(text, max_len=12) == text


def test_press_reply_to_limit_truncates_at_space_separator() -> None:
    pressed = _press_reply_to_limit("早上好 今天天气真不错呀 出去走走吧", max_len=10)
    assert len(pressed) <= 10
    assert pressed == "早上好"


def test_resolve_output_filtered_reply_presses_overlength_short_band() -> None:
    task = {"task_type": LLM_CHAT_TASK_TYPE, "reply_max_length": 12}
    reply = "哎呀这个我回头帮你查查。【我们吃个饭吧】。行了先这样。"
    filtered = resolve_output_filtered_reply(task, reply)
    assert filtered == "哎呀这个我回头帮你查查。"
    assert len(filtered) <= 12


def test_resolve_output_filtered_reply_keeps_multi_bubble_when_each_fits() -> None:
    """多泡回复：每个气泡各自落在上限内时保持分条，而不是整串 join 后一刀切静默。"""
    task = {"task_type": LLM_CHAT_TASK_TYPE, "reply_max_length": 24}
    reply = '{"reply_segments":["这是土狼，会搞笑。","然后呢？","别怕别怕。"]}'
    filtered = resolve_output_filtered_reply(task, reply)
    assert filtered == "这是土狼，会搞笑。\n然后呢？\n别怕别怕。"
    for segment in filtered.split("\n"):
        assert len(segment) <= 24
