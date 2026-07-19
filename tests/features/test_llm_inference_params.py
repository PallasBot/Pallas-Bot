from __future__ import annotations

from pallas.product.llm.config import resolve_llm_repeater_flags, resolve_llm_repeater_mode
from pallas.product.llm.inference_params import chat_token_count_with_tools, derive_llm_inference_params
from pallas.product.persona.model import ResolvedPersona


def test_derive_llm_inference_params_short_persona() -> None:
    persona = ResolvedPersona(length_pref="short", chaos_bias=0.0, warmth=0.0, assertiveness=0.0)
    temperature, token_count = derive_llm_inference_params(persona, mode="normal", purpose="chat")
    assert temperature == 0.55
    assert token_count == 128


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
    assert token_count == 240


def test_derive_llm_inference_params_polish_caps_tokens() -> None:
    persona = ResolvedPersona(length_pref="long")
    _, token_count = derive_llm_inference_params(persona, mode="normal", purpose="polish")
    assert token_count == 96


def test_derive_llm_inference_params_select() -> None:
    persona = ResolvedPersona(length_pref="long", chaos_bias=0.5)
    temperature, token_count = derive_llm_inference_params(persona, mode="normal", purpose="select")
    assert temperature == 0.28
    assert token_count == 48


def test_derive_llm_inference_params_polish_lite() -> None:
    persona = ResolvedPersona(length_pref="long")
    temperature, token_count = derive_llm_inference_params(persona, mode="normal", purpose="polish_lite")
    assert temperature == 0.35
    assert token_count == 80


def test_derive_llm_inference_params_fallback_lite() -> None:
    persona = ResolvedPersona(length_pref="long")
    temperature, token_count = derive_llm_inference_params(persona, mode="normal", purpose="fallback_lite")
    assert temperature == 0.42
    assert token_count == 128


def test_chat_token_count_with_tools_floor() -> None:
    assert chat_token_count_with_tools(128, tools_enabled=True) == 280
    assert chat_token_count_with_tools(128, tools_enabled=False) == 128
    assert chat_token_count_with_tools(None, tools_enabled=True) == 280
    assert chat_token_count_with_tools(None, tools_enabled=False) is None


def test_resolve_llm_repeater_mode_default_select(monkeypatch) -> None:
    monkeypatch.setattr("pallas.product.llm.config.repo_env_raw_value", lambda key: None)
    assert resolve_llm_repeater_mode() == "select"
    assert resolve_llm_repeater_flags() == (False, False, True)


def test_resolve_llm_repeater_mode_from_legacy_flags(monkeypatch) -> None:
    def fake_raw(key: str) -> str | None:
        values = {
            "LLM_REPEATER_MODE": "",
            "LLM_FALLBACK_ENABLED": "true",
            "LLM_POLISH_ENABLED": "false",
        }
        raw = values.get(key)
        return raw or None

    monkeypatch.setattr("pallas.product.llm.config.repo_env_raw_value", fake_raw)
    assert resolve_llm_repeater_mode() == "fallback"
    assert resolve_llm_repeater_flags() == (True, False, False)


def test_resolve_llm_repeater_mode_explicit_both(monkeypatch) -> None:
    def fake_raw(key: str) -> str | None:
        values = {
            "LLM_REPEATER_MODE": "both",
            "LLM_FALLBACK_ENABLED": "false",
            "LLM_POLISH_ENABLED": "false",
        }
        return values.get(key)

    monkeypatch.setattr("pallas.product.llm.config.repo_env_raw_value", fake_raw)
    assert resolve_llm_repeater_mode() == "both"
    assert resolve_llm_repeater_flags() == (True, True, False)


def test_resolve_llm_repeater_mode_select_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.config.repo_env_raw_value",
        lambda key: "select_fallback" if key == "LLM_REPEATER_MODE" else None,
    )
    assert resolve_llm_repeater_mode() == "select_fallback"
    assert resolve_llm_repeater_flags() == (True, False, True)
