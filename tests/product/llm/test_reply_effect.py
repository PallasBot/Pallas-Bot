from __future__ import annotations

import json

from pallas.product.llm.reply_effect import (
    append_reply_effect_record,
    build_reply_effect_prompt,
    has_rejection_tone,
    heuristic_reply_effect_scores,
    parse_reply_effect_scores,
)


def test_heuristic_flags_service_tone_as_uncanny() -> None:
    scores = heuristic_reply_effect_scores("您好，有什么可以帮您的吗？")
    assert scores["uncanny_risk"] >= 4
    assert scores["appropriateness"] <= 3


def test_heuristic_ok_for_casual_chat() -> None:
    scores = heuristic_reply_effect_scores("那就先这样吧")
    assert scores["uncanny_risk"] <= 3
    assert scores["social_presence"] >= 3


def test_parse_reply_effect_scores_json() -> None:
    payload = parse_reply_effect_scores(
        '{"social_presence":{"score":4},"warmth":{"score":3},"competence":{"score":3},'
        '"appropriateness":{"score":4},"uncanny_risk":{"score":2}}'
    )
    assert payload["social_presence"] == 4
    assert payload["uncanny_risk"] == 2


def test_append_reply_effect_record(tmp_path) -> None:
    path = tmp_path / "eval.jsonl"
    append_reply_effect_record(
        {"reply_text": "行", "scores": heuristic_reply_effect_scores("行")},
        path=path,
    )
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["reply_text"] == "行"


def test_build_reply_effect_prompt_contains_axes() -> None:
    prompt = build_reply_effect_prompt("哈哈", followups=["确实"])
    assert "uncanny_risk" in prompt
    assert "哈哈" in prompt


def test_heuristic_flags_rejection_tone() -> None:
    assert has_rejection_tone("想得美，自己挣去")
    assert has_rejection_tone("少来这套，哭也没用")
    assert has_rejection_tone("别吵我")
    assert has_rejection_tone("自己挨去")


def test_heuristic_clears_warm_and_neutral_replies() -> None:
    assert not has_rejection_tone("那就先这样吧")
    assert not has_rejection_tone("你好呀，想聊点什么")
    assert not has_rejection_tone("早，今天天气不错")


def test_evaluate_record_carries_rejection_tone_flag(tmp_path) -> None:
    from pallas.product.llm.reply_effect import evaluate_and_record_reply_effect

    path = tmp_path / "eval.jsonl"
    evaluate_and_record_reply_effect("想得美，自己挣去", path=path)
    evaluate_and_record_reply_effect("那就先这样吧", path=path)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(lines[0])["rejection_tone"] is True
    assert json.loads(lines[1])["rejection_tone"] is False
