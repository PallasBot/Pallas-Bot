from __future__ import annotations

import json

from pallas.product.llm.reply_effect import (
    append_reply_effect_record,
    build_reply_effect_prompt,
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
