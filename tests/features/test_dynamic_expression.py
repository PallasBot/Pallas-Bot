from __future__ import annotations

from pallas.product.persona.dynamic_expression import (
    build_affect_trigger_turn_hint,
    clean_expression_reference_text,
    format_dynamic_expression_hint,
    format_situational_expression_pairs,
    is_usable_expression_reference,
    match_message_affect_triggers,
)


def test_match_message_affect_triggers_matches_substring() -> None:
    triggers = [
        {"phrase": "牛牛税", "weight": 1.0, "warmth_delta": 0.1},
        {"phrase": "开黑", "weight": 0.5, "warmth_delta": -0.1},
    ]
    matched = match_message_affect_triggers("今天牛牛税又涨了", triggers)

    assert len(matched) == 1
    assert matched[0]["phrase"] == "牛牛税"


def test_build_affect_trigger_turn_hint_describes_tone_shift() -> None:
    hint = build_affect_trigger_turn_hint(
        "别吵了开黑吧",
        [{"phrase": "开黑", "warmth_delta": 0.12, "assertiveness_delta": 0.15}],
    )

    assert hint.startswith("【情境触发】")
    assert "开黑" in hint
    assert "更接梗" in hint
    assert "顶一句" in hint


def test_format_situational_expression_pairs_pairs_trigger_with_candidate() -> None:
    lines = format_situational_expression_pairs(
        [{"phrase": "牛牛税"}],
        ["那确实，有点道理", "有点狠但还行"],
        user_text="今天牛牛税多少",
    )

    assert len(lines) == 1
    assert "牛牛税" in lines[0]
    assert "那确实" in lines[0]
    assert "勿照抄" in lines[0]


def test_is_usable_expression_reference_rejects_cq_and_fragments() -> None:
    assert not is_usable_expression_reference("[CQ:at,qq=123] 你快")
    assert not is_usable_expression_reference("诶")
    assert not is_usable_expression_reference("3498")
    assert is_usable_expression_reference("然后呢")
    assert is_usable_expression_reference("你都喊成这样了，还不进来那也太不给面子了")


def test_clean_expression_reference_text_strips_cq() -> None:
    assert clean_expression_reference_text("[CQ:at,qq=123] 你快进来呀") == "你快进来呀"


def test_format_dynamic_expression_hint_joins_sections() -> None:
    hint = format_dynamic_expression_hint(
        "【情境触发】提到「开黑」时，按本群习惯接话",
        ["当「开黑」时，可参考本群说法「来一把吧，走起」"],
    )

    assert "【情境触发】" in hint
    assert "【表达习惯参考】" in hint
    assert hint.endswith("。")
