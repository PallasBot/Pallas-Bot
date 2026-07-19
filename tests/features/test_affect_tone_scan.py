from __future__ import annotations

from pallas.core.foundation.paths import resource_dir
from pallas.product.persona.affect_baseline import derive_group_affect_bias
from pallas.product.persona.affect_lexicon import parse_lexicon_sections, punct_aggression_score, resolve_lexicon_path
from pallas.product.persona.affect_tone_scan import scan_plain_tone, summarize_group_message_tones
from pallas.product.persona.compile_group_style import build_group_style_hints


def test_baseline_lexicon_path_under_resource() -> None:
    path = resource_dir("persona", "affect_lexicon_baseline.txt")
    assert path.is_file()
    sections = parse_lexicon_sections(path.read_text(encoding="utf-8"))
    assert "谢谢" in sections["polite"]
    assert "离谱" in sections["harsh"]


def test_resolve_lexicon_path_relative_to_repo_root() -> None:
    resolved = resolve_lexicon_path("resource/persona/affect_lexicon_baseline.txt")
    assert resolved.is_file()
    sections = parse_lexicon_sections("# comment\n[polite]\n谢谢\n辛苦\n[harsh]\n离谱\n\n# tail\n")
    assert sections["polite"] == ["谢谢", "辛苦"]
    assert sections["harsh"] == ["离谱"]


def test_punct_aggression_score() -> None:
    assert punct_aggression_score("你好") == 0.0
    assert punct_aggression_score("什么？？？") > punct_aggression_score("什么")


def test_summarize_group_message_tones_polite_vs_harsh() -> None:
    polite = summarize_group_message_tones(["谢谢辛苦", "收到好的", "请问可以吗"])
    harsh = summarize_group_message_tones(["卧槽离谱", "滚蛋别烦", "什么玩意？？？"])
    assert polite["civility_score"] > harsh["civility_score"]
    assert polite["polite_msg_ratio"] > 0.0
    assert harsh["harsh_msg_ratio"] > 0.0


def test_scan_plain_tone_flags() -> None:
    from pallas.product.persona.affect_lexicon import load_affect_lexicon

    lex = load_affect_lexicon()
    flags = scan_plain_tone(
        "谢谢啦",
        polite_patterns=lex["polite"],
        harsh_patterns=lex["harsh"],
    )
    assert flags["polite_hit"] is True
    assert flags["harsh_hit"] is False


def test_civility_raises_warmth_and_lowers_assertiveness() -> None:
    base = derive_group_affect_bias(
        repeat_chain_rate=0.1,
        short_message_ratio=0.2,
        local_answer_ratio=0.2,
    )
    polite = derive_group_affect_bias(
        repeat_chain_rate=0.1,
        short_message_ratio=0.2,
        local_answer_ratio=0.2,
        civility_score=0.6,
        polite_msg_ratio=0.5,
    )
    harsh = derive_group_affect_bias(
        repeat_chain_rate=0.1,
        short_message_ratio=0.2,
        local_answer_ratio=0.2,
        civility_score=-0.6,
        harsh_msg_ratio=0.4,
        punct_aggression_avg=0.3,
    )
    assert polite["warmth_bias"] >= base["warmth_bias"]
    assert polite["assertiveness_bias"] <= harsh["assertiveness_bias"]


def test_build_group_style_hints_civility() -> None:
    polite_hints = build_group_style_hints({"civility_score": 0.4})
    harsh_hints = build_group_style_hints({"civility_score": -0.4})
    assert "群聊语气偏文明客气" in polite_hints
    assert "群聊语气偏直接或有冲突用语" in harsh_hints
