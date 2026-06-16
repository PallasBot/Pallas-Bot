from __future__ import annotations

from src.features.llm.config import resolve_llm_repeater_flags, resolve_llm_repeater_mode
from src.features.llm.inference_params import derive_llm_inference_params
from src.features.persona.model import ResolvedPersona


def test_derive_llm_inference_params_short_persona() -> None:
    persona = ResolvedPersona(length_pref="short", chaos_bias=0.0, warmth=0.0, assertiveness=0.0)
    temperature, token_count = derive_llm_inference_params(persona, mode="normal", purpose="chat")
    assert temperature == 0.55
    assert token_count == 80


def test_derive_llm_inference_params_chaotic_warm() -> None:
    persona = ResolvedPersona(length_pref="long", chaos_bias=0.4, warmth=0.3, assertiveness=0.2)
    temperature, token_count = derive_llm_inference_params(persona, mode="normal", purpose="fallback")
    assert temperature is not None
    assert temperature > 0.55
    assert token_count == 160


def test_derive_llm_inference_params_drunk_skips_temperature() -> None:
    persona = ResolvedPersona(length_pref="medium")
    temperature, token_count = derive_llm_inference_params(persona, mode="drunk", purpose="chat")
    assert temperature is None
    assert token_count == 120


def test_derive_llm_inference_params_polish_caps_tokens() -> None:
    persona = ResolvedPersona(length_pref="long")
    _, token_count = derive_llm_inference_params(persona, mode="normal", purpose="polish")
    assert token_count == 96


def test_resolve_llm_repeater_mode_default_both(monkeypatch) -> None:
    monkeypatch.setattr("src.features.llm.config.repo_env_raw_value", lambda key: None)
    assert resolve_llm_repeater_mode() == "both"
    assert resolve_llm_repeater_flags() == (True, True)


def test_resolve_llm_repeater_mode_from_legacy_flags(monkeypatch) -> None:
    def fake_raw(key: str) -> str | None:
        values = {
            "LLM_REPEATER_MODE": "",
            "LLM_FALLBACK_ENABLED": "true",
            "LLM_POLISH_ENABLED": "false",
        }
        raw = values.get(key)
        return raw or None

    monkeypatch.setattr("src.features.llm.config.repo_env_raw_value", fake_raw)
    assert resolve_llm_repeater_mode() == "fallback"
    assert resolve_llm_repeater_flags() == (True, False)


def test_resolve_llm_repeater_mode_explicit_both(monkeypatch) -> None:
    def fake_raw(key: str) -> str | None:
        values = {
            "LLM_REPEATER_MODE": "both",
            "LLM_FALLBACK_ENABLED": "false",
            "LLM_POLISH_ENABLED": "false",
        }
        return values.get(key)

    monkeypatch.setattr("src.features.llm.config.repo_env_raw_value", fake_raw)
    assert resolve_llm_repeater_mode() == "both"
    assert resolve_llm_repeater_flags() == (True, True)
