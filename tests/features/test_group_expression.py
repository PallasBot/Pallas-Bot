from __future__ import annotations

from pallas.product.persona.group_expression import compile_group_expression_prompt


def test_compile_group_expression_prompt_uses_affect_trigger_phrase() -> None:
    prompt = compile_group_expression_prompt({
        "sample": {
            "message_count": 120,
            "answer_count": 24,
            "affect_triggers": [
                {"phrase": "牛牛税"},
                {"phrase": "开一把"},
            ],
        },
        "raw": {
            "repeat_chain_rate": 0.22,
            "affect_tone": {"civility_score": -0.3},
        },
        "derived": {
            "length_pref": "short",
            "chaos_bias": 0.18,
        },
    })

    assert "<<STATS:group_expression>>" in prompt
    assert "更像顺手短句" in prompt
    assert "复读链和接梗较常见" in prompt
    assert "整体语气更直接" in prompt
    assert "牛牛税" in prompt
    assert "开一把" in prompt


def test_compile_group_expression_prompt_mentions_high_chaos_short_replies() -> None:
    prompt = compile_group_expression_prompt({
        "sample": {"message_count": 100, "answer_count": 20},
        "raw": {
            "repeat_chain_rate": 0.12,
            "affect_tone": {"civility_score": 0.0},
        },
        "derived": {
            "length_pref": "short",
            "chaos_bias": 0.2,
        },
    })

    assert "短句" in prompt
    assert "别一开口就解释太满" in prompt
