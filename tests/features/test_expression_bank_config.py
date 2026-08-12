from __future__ import annotations

import os

import pytest

from pallas.product.llm.config import LlmConfig, clear_llm_config_cache, get_llm_config


def test_expression_bank_config_defaults() -> None:
    cfg = LlmConfig()

    assert cfg.llm_expression_inject_enabled is True
    assert cfg.llm_expression_learn_enabled is True
    assert cfg.llm_expression_auto_promote_enabled is True
    assert cfg.llm_expression_retrieve_limit == 5


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("0", 1),
        ("9", 8),
    ],
)
def test_expression_retrieve_limit_is_clamped_from_env(
    monkeypatch: pytest.MonkeyPatch,
    raw_value: str,
    expected: int,
) -> None:
    from pallas.product.llm import config as llm_config

    monkeypatch.setenv("LLM_EXPRESSION_RETRIEVE_LIMIT", raw_value)
    monkeypatch.setattr(
        llm_config,
        "repo_env_raw_value",
        lambda key: os.environ.get(key),
    )
    clear_llm_config_cache()

    assert get_llm_config().llm_expression_retrieve_limit == expected

    clear_llm_config_cache()
