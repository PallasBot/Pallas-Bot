from __future__ import annotations

from pallas.product.persona.expression_habits import (
    build_expression_habits_suffix,
    compile_expression_habits_lines,
)


def test_compile_expression_habits_lines_prefers_phrase_and_dedupes() -> None:
    lines = compile_expression_habits_lines({
        "sample": {
            "affect_triggers": [
                {"phrase": "牛牛税"},
                {"phrase": "牛牛税"},
                {"trigger": "开一把"},
                {"text": "来都来了"},
            ]
        }
    })

    assert lines == [
        "群里常接这些说法/梗：牛牛税、开一把、来都来了",
    ]


def test_build_expression_habits_suffix_includes_short_chaos_hint() -> None:
    suffix = build_expression_habits_suffix({
        "sample": {"affect_triggers": [{"phrase": "牛牛税"}]},
        "derived": {"length_pref": "short", "chaos_bias": 0.2},
    })

    assert suffix.startswith("\n【表达习惯参考】")
    assert "牛牛税" in suffix
    assert "顺手短句" in suffix
