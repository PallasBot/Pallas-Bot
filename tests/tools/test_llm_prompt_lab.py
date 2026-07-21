from __future__ import annotations

import json

from tools.llm_prompt_lab import load_fixtures, score_fixture


def test_prompt_lab_scores_fixture_rows(tmp_path) -> None:
    fixtures = tmp_path / "f.jsonl"
    fixtures.write_text(
        json.dumps(
            {
                "user_text": "你是不是AI",
                "model_output": "您好，有什么可以帮您？",
                "scene": "provocation",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    rows = load_fixtures(fixtures)
    result = score_fixture(rows[0])
    assert result["low_score"] is True
    assert result["draft_constraint"]
