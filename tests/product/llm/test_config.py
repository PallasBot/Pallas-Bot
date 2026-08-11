from __future__ import annotations

from typing import TYPE_CHECKING

from pallas.product.llm import config as mod

if TYPE_CHECKING:
    import pytest


def test_current_turn_decision_model_default_is_disabled() -> None:
    assert mod.LlmConfig().llm_current_turn_decision_enabled is False


def test_current_turn_decision_env_default_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "repo_env_raw_value", lambda _key: None)
    mod.clear_llm_config_cache()
    try:
        assert mod.get_llm_config().llm_current_turn_decision_enabled is False
    finally:
        mod.clear_llm_config_cache()
