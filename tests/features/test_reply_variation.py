from __future__ import annotations

from types import SimpleNamespace

from pallas.product.llm.reply_variation import (
    build_recent_reply_ending_hint,
    build_recent_reply_variation_hint,
    build_variation_hint_from_recent_texts,
    classify_repeated_opener,
    extract_recent_motifs,
    repeated_assistant_openers,
    should_wait_for_more,
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


def test_classify_repeated_opener_detects_soft_agree() -> None:
    assert classify_repeated_opener("行行行，我闭嘴就是。") == "行行行"
    assert classify_repeated_opener("还行吧，主要看你会不会玩。") == "还行吧"
    assert classify_repeated_opener("好好好，文明点。") == "好好好"


def test_build_recent_reply_variation_hint_flags_soft_agree_openers() -> None:
    turns = [
        SimpleNamespace(role="assistant", content="行行行，你说了算。"),
        SimpleNamespace(role="assistant", content="行行行，我闭嘴就是。"),
        SimpleNamespace(role="assistant", content="还行吧，至少没被炖了。"),
    ]
    hint = build_recent_reply_variation_hint(turns)
    assert "行行行" in hint
    assert "软答应" in hint or "还行吧" in hint


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


def test_motif_hint_from_recent_texts() -> None:
    hint = build_variation_hint_from_recent_texts([
        "双倍草料，土木牛牛明天干活都有劲了。",
        "草料管够就行",
        "再来一份草料垫垫肚子。",
    ])
    assert "草料" in hint


def test_extract_recent_motifs_detects_repeated_ngrams() -> None:
    motifs = extract_recent_motifs([
        "双倍草料，土木牛牛明天干活都有劲了。",
        "漂亮牛牛今天也得吃草料。",
        "草料管够就行。",
    ])
    assert "草料" in motifs


def test_extract_recent_motifs_catches_sticky_horn_without_blacklist() -> None:
    motifs = extract_recent_motifs([
        "兑？我这牛角可不能兑，留着顶门用呢。",
        "撞死你？那我得先热热身，牛角可金贵着呢。",
        "牛角割了可没法再长，我留着顶门用呢。",
        "嘿，说我蠢？牛角给你当棒球棍耍是吧。",
    ])
    assert "牛角" in motifs
    hint = build_variation_hint_from_recent_texts([
        "兑？我这牛角可不能兑，留着顶门用呢。",
        "撞死你？那我得先热热身，牛角可金贵着呢。",
        "牛角割了可没法再长，我留着顶门用呢。",
    ])
    assert "复读对方词" in hint
    assert "牛角" in hint


def test_compile_self_identity_prompt_mentions_niu_niu() -> None:
    prompt = compile_self_identity_prompt()
    assert "牛牛" in prompt
    assert "第一人称" in prompt
    assert "不是物种" in prompt


def test_explicit_mention_question_does_not_wait_for_more() -> None:
    assert should_wait_for_more("你是不是只会哞哞叫？", is_to_me=True) is False
    assert should_wait_for_more("你是不是只会哞哞叫？") is True
