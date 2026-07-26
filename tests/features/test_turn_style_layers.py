"""本轮行为/措辞分层、同句重回与概率换风格。"""

from __future__ import annotations

import random
from types import SimpleNamespace

from pallas.product.llm.models import ChatCompletionMessage
from pallas.product.llm.turn_style_layers import (
    ReplyStyleVariantPolicy,
    build_probabilistic_alt_style_hint,
    select_reply_style_variant,
    build_same_utterance_redup_hint,
    build_turn_behavior_block,
    build_turn_wording_user_hints,
    find_previous_reply_for_utterance,
    merge_style_hints_before_last_user,
    normalize_utterance_key,
)
from pallas.product.persona.catchphrase_bank import (
    compile_catchphrase_prompt_lines,
    list_catchphrases,
    promote_catchphrase,
    propose_catchphrase_from_bot_success,
    select_catchphrases_for_turn,
)


def test_normalize_utterance_key_strips_ws() -> None:
    assert normalize_utterance_key("行  行行") == normalize_utterance_key("行行行")


def test_find_previous_reply_from_behavior_run() -> None:
    runs = [
        SimpleNamespace(user_text="你怎么一直嗯嗯嗯", reply_text="嗯？"),
        SimpleNamespace(user_text="翻译成中文", reply_text="漂亮牛说想咬我"),
    ]
    assert find_previous_reply_for_utterance("翻译成中文", behavior_runs=runs) == "漂亮牛说想咬我"


def test_find_previous_reply_from_turns() -> None:
    turns = [
        SimpleNamespace(role="user", content="牛牛坏掉了"),
        SimpleNamespace(role="assistant", content="没坏，就是懒得动而已。"),
        SimpleNamespace(role="user", content="别的"),
    ]
    assert "懒得动" in find_previous_reply_for_utterance("牛牛坏掉了", recent_turns=turns)


def test_same_utterance_redup_hint() -> None:
    hint = build_same_utterance_redup_hint(user_text="翻译成中文", previous_reply="漂亮牛说想咬我")
    assert "同句重回" in hint
    assert "漂亮牛说想咬我" in hint
    assert "换说法" in hint


def test_probabilistic_alt_style_respects_rng() -> None:
    always = build_probabilistic_alt_style_hint(probability=1.0, rng=random.Random(0))
    never = build_probabilistic_alt_style_hint(probability=0.0, rng=random.Random(0))
    assert always.startswith("【本轮临时措辞】")
    assert never == ""


def test_affect_variant_selection_is_bounded_and_seeded() -> None:
    policy = ReplyStyleVariantPolicy(
        enabled=True,
        base_probability=2.0,
        affect_styles={"warm": ["playful"], "default": ["direct"]},
    )
    selected = select_reply_style_variant(
        policy,
        affect_class="warm",
        rng=random.Random(0),
    )
    assert selected.style_class == "playful"
    assert selected.applied is True


def test_affect_variant_keeps_legacy_fallback_without_affect() -> None:
    selected = select_reply_style_variant(
        ReplyStyleVariantPolicy(base_probability=1.0),
        affect_class="",
        rng=random.Random(0),
    )
    assert selected.applied is True
    assert selected.style_class


def test_behavior_and_wording_split() -> None:
    behavior = build_turn_behavior_block("【本轮行为参考】\n- 短回", "")
    assert "只管怎么接" in behavior
    hints = build_turn_wording_user_hints("【表达参考】x", "", "【同句重回】y")
    assert hints == ["【表达参考】x", "【同句重回】y"]


def test_merge_style_hints_before_last_user() -> None:
    messages = [
        ChatCompletionMessage(role="user", content="hi"),
        ChatCompletionMessage(role="assistant", content="yo"),
        ChatCompletionMessage(role="user", content="翻译成中文"),
    ]
    merged = merge_style_hints_before_last_user(messages, ["【本轮临时措辞】短一点"])
    assert [m.role for m in merged] == ["user", "assistant", "user", "user"]
    assert merged[-2].content.startswith("【本轮临时措辞】")
    assert merged[-1].content == "翻译成中文"


def test_catchphrase_selects_by_scene_and_text(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    propose_catchphrase_from_bot_success(42, 1, "那很牛了", "接梗玩笑")
    propose_catchphrase_from_bot_success(42, 2, "那很牛了", "接梗玩笑")
    propose_catchphrase_from_bot_success(42, 3, "那很牛了", "接梗玩笑")

    row = next(item for item in list_catchphrases(42) if item.saying == "那很牛了")
    promote_catchphrase(row.entry_id, force=True)
    picked = select_catchphrases_for_turn(42, user_text="这个梗典炸了", scene="banter", limit=2)
    assert picked
    assert picked[0].saying == "那很牛了"
    lines = compile_catchphrase_prompt_lines(42, user_text="这个梗典炸了", scene="banter", limit=2)
    assert any("那很牛了" in line for line in lines)
    assert compile_catchphrase_prompt_lines(42, limit=0) == []


def test_catchphrase_canonical_venting_occasion_matches_legacy_variant(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    row = propose_catchphrase_from_bot_success(42, 1, "太难了", "吐槽加班")
    assert row is not None
    assert row.occasion == "venting"
    promote_catchphrase(row.entry_id, force=True)
    picked = select_catchphrases_for_turn(42, user_text="加班太难了", scene="venting", limit=1)
    assert [item.entry_id for item in picked] == [row.entry_id]


def test_catchphrase_rejects_canonical_scene_mismatch_despite_keyword(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    row = propose_catchphrase_from_bot_success(42, 1, "太难了", "吐槽加班")
    assert row is not None
    promote_catchphrase(row.entry_id, force=True)
    assert select_catchphrases_for_turn(42, user_text="加班太难了", scene="banter", limit=1) == []
