from __future__ import annotations

from types import SimpleNamespace

from pallas.product.llm.reply_variation import (
    build_recent_reply_ending_hint,
    build_recent_reply_variation_hint,
    classify_repeated_opener,
    repeated_assistant_openers,
)
from pallas.product.persona.self_identity import compile_self_identity_prompt


def test_build_recent_reply_ending_hint_collects_natural_endings() -> None:
    turns = [
        SimpleNamespace(role="assistant", content="其实就是这样"),
        SimpleNamespace(role="assistant", content="那也不是不行。"),
        SimpleNamespace(role="assistant", content="行啊"),
    ]

    hint = build_recent_reply_ending_hint(turns)

    assert hint.startswith("\n【收尾变化参考】")
    assert "就是这样"[-4:] in hint
    assert "不是不行"[-4:] in hint
    assert "行啊" in hint


def test_build_recent_reply_ending_hint_skips_kaomoji_dominated_history() -> None:
    turns = [
        SimpleNamespace(role="assistant", content="哞~ 好呀！(*^_^*)"),
        SimpleNamespace(role="assistant", content="喵~ 行！(*^ω^*)"),
        SimpleNamespace(role="assistant", content="嗯嗯 (*^_^*)"),
    ]

    assert build_recent_reply_ending_hint(turns) == ""


def test_classify_repeated_opener_detects_animal_prefix() -> None:
    assert classify_repeated_opener("哞~ 今天不错") == "哞~"
    assert classify_repeated_opener("喵~ 你说得对") == "喵~"


def test_classify_repeated_opener_ignores_numeric_prefix() -> None:
    assert classify_repeated_opener("3498 某种回复") == ""
    assert classify_repeated_opener("你快") == ""


def test_build_recent_reply_variation_hint_flags_animal_and_kaomoji() -> None:
    turns = [
        SimpleNamespace(role="assistant", content="哞~ 谢谢啦！(*^_^*)"),
        SimpleNamespace(role="assistant", content="喵~ 找到了！(*^_^*)"),
        SimpleNamespace(role="assistant", content="喵~ 你说得对！(*^_^*)"),
    ]

    hint = build_recent_reply_variation_hint(turns)

    assert "哞~" in hint or "喵~" in hint
    assert "颜文字" in hint
    assert repeated_assistant_openers(turns)


def test_compile_self_identity_prompt_mentions_niu_niu() -> None:
    prompt = compile_self_identity_prompt()
    assert "牛牛" in prompt
    assert "第一人称" in prompt
    assert "牛牛真棒" in prompt
