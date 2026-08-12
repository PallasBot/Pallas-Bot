from __future__ import annotations

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.reply_postprocess import (
    apply_chinese_typo,
    apply_reply_postprocess,
    split_short_reply_segments,
    trim_terminal_period,
)


def test_typo_disabled_returns_original() -> None:
    assert apply_chinese_typo("今天真的很好", error_rate=0.0, rng_seed=1) == "今天真的很好"


def test_typo_can_change_with_high_rate() -> None:
    out = apply_chinese_typo("的了是在有", error_rate=1.0, rng_seed=7)
    assert out != "的了是在有" or len(out) == len("的了是在有")
    assert len(out) == len("的了是在有")


def test_apply_reply_postprocess_off_passthrough() -> None:
    assert apply_reply_postprocess("你好呀", enabled=False) == "你好呀"


def test_trim_terminal_period_only_changes_a_short_single_statement() -> None:
    assert trim_terminal_period("行吧。", trim_rate=1.0, rng_seed=1) == "行吧"


def test_trim_terminal_period_default_rate_is_ninety_percent() -> None:
    assert LlmConfig().llm_reply_trim_terminal_period_rate == 0.9


def test_trim_terminal_period_keeps_questions_emphasis_and_long_or_multi_sentence_text() -> None:
    assert trim_terminal_period("你确定？", trim_rate=1.0, rng_seed=1) == "你确定？"
    assert trim_terminal_period("这也太离谱了！", trim_rate=1.0, rng_seed=1) == "这也太离谱了！"
    assert trim_terminal_period("第一句。第二句。", trim_rate=1.0, rng_seed=1) == "第一句。第二句。"
    text = "这个问题我得先核对一下上下文和已经整理的历史记录再说。"
    assert trim_terminal_period(text, trim_rate=1.0, rng_seed=1) == text


def test_split_short_reply_splits_at_sentence_endings() -> None:
    assert split_short_reply_segments("想得美。你谁啊你") == ["想得美。", "你谁啊你"]


def test_split_short_reply_splits_newline_separated_bubbles() -> None:
    assert split_short_reply_segments("想得美\n\n你谁啊你") == ["想得美", "你谁啊你"]


def test_split_short_reply_splits_newlines_within_sentence_segments() -> None:
    assert split_short_reply_segments("六点？\n你真狠\n我努力一下") == ["六点？", "你真狠", "我努力一下"]


def test_split_short_reply_caps_at_three_bubbles() -> None:
    assert split_short_reply_segments("一。\n二\n三\n四") == ["一。", "二", "三\n四"]


def test_split_short_reply_keeps_plain_single_line_unchanged() -> None:
    assert split_short_reply_segments("想你") == ["想你"]


def test_split_newline_only_mode_ignores_sentence_punctuation() -> None:
    assert split_short_reply_segments(
        "六点？你真狠。\n我努力一下。",
        split_by_punctuation=False,
    ) == ["六点？你真狠。", "我努力一下。"]


def test_split_newline_only_mode_caps_at_max_segments() -> None:
    assert split_short_reply_segments(
        "一。\n二\n三\n四",
        split_by_punctuation=False,
        max_segments=2,
    ) == ["一。", "二\n三\n四"]
