from __future__ import annotations

from pallas.product.llm.config import (
    resolve_llm_polish_lite_enabled,
    resolve_llm_repeater_flags,
    resolve_llm_repeater_mode,
)
from pallas.product.llm.polish_lite import (
    build_polish_lite_user_text,
    build_polish_lite_user_text_with_suffix,
    should_polish_lite_sample,
)


def test_build_polish_lite_user_text() -> None:
    text = build_polish_lite_user_text("夜宵吃什么", "小炒黄牛肉")
    assert "【用户消息】夜宵吃什么" in text
    assert "【候选回复】小炒黄牛肉" in text
    assert "勿加设定词" in text
    assert "继续聊" in text


def test_load_polish_lite_system_prompt_forbids_expansion() -> None:
    from pallas.product.persona.compile_persona_prompt import load_polish_lite_system_prompt

    text = load_polish_lite_system_prompt()
    assert "禁止扩写" in text
    assert "继续聊" in text


def test_build_polish_lite_user_text_with_expression_habits() -> None:
    text = build_polish_lite_user_text_with_suffix(
        "夜宵吃什么",
        "小炒黄牛肉",
        style_suffix="【表达习惯参考】群里常接这些说法/梗：牛牛税。",
    )
    assert "表达习惯参考" in text
    assert "牛牛税" in text


def test_should_polish_lite_sample_deterministic() -> None:
    first = should_polish_lite_sample(1, 2, 99, sample_rate=0.5)
    second = should_polish_lite_sample(1, 2, 99, sample_rate=0.5)
    assert first == second


def test_resolve_select_polish_lite_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.config.repo_env_raw_value",
        lambda key: "select_polish_lite" if key == "LLM_REPEATER_MODE" else None,
    )
    assert resolve_llm_repeater_mode() == "select_polish_lite"
    assert resolve_llm_repeater_flags() == (False, False, True)
    assert resolve_llm_polish_lite_enabled() is True
