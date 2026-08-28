from __future__ import annotations

import ast
from pathlib import Path

import pytest

from pallas.product.llm.config import (
    LlmConfig,
)
from pallas.product.llm.inference_params import (
    chat_reply_token_budget,
    derive_llm_inference_params,
    resolve_task_token_budget,
    task_token_budget,
)
from pallas.product.llm.tool_loop import inference_options_from_metadata
from pallas.product.persona.account_profile import AccountPersonaProfile
from pallas.product.persona.model import ResolvedPersona


def test_derive_llm_inference_params_uses_chat_task_budget() -> None:
    persona = ResolvedPersona(chaos_bias=0.0, warmth=0.0, assertiveness=0.0)
    temperature, token_count = derive_llm_inference_params(persona, mode="normal")
    assert temperature == 0.7
    assert token_count == 240


def test_derive_llm_inference_params_chaotic_warm() -> None:
    persona = ResolvedPersona(chaos_bias=0.4, warmth=0.3, assertiveness=0.2)
    temperature, token_count = derive_llm_inference_params(persona, mode="normal")
    assert temperature is not None
    assert temperature > 0.7
    assert token_count == 240


def test_derive_llm_inference_params_drunk_skips_temperature() -> None:
    persona = ResolvedPersona()
    temperature, token_count = derive_llm_inference_params(persona, mode="drunk")
    assert temperature is None
    assert token_count == 240


@pytest.mark.parametrize(
    ("task", "tools_enabled", "expected"),
    [
        ("llm_chat", False, 240),
        ("llm_chat", True, 360),
        ("affect_refine", False, 512),
        ("memory_extract", False, 160),
        ("turn_decision", False, 48),
        ("repeater.semantic_style", False, 96),
        ("sticker_vision", False, 32),
        ("vision_messages", False, 256),
        ("memory_graph_extract", False, 1200),
        ("memory_graph_hiergraph", False, 1500),
        ("offline_quality_eval", False, 96),
    ],
)
def test_task_token_budget(task: str, tools_enabled: bool, expected: int) -> None:
    assert task_token_budget(task, tools_enabled=tools_enabled) == expected


def test_account_profile_does_not_change_token_budget() -> None:
    quiet = ResolvedPersona(account_profile=AccountPersonaProfile(restraint=1.0))
    lively = ResolvedPersona(account_profile=AccountPersonaProfile(energy=1.0, mischief=1.0))
    assert derive_llm_inference_params(quiet)[1] == derive_llm_inference_params(lively)[1] == 240


@pytest.mark.parametrize(
    ("band", "tools_enabled", "expected"),
    [
        ("casual", False, 240),
        ("serious", False, 256),
        ("tool", True, 512),
    ],
)
def test_chat_reply_budget_reaches_final_task_resolution(
    band: str,
    tools_enabled: bool,
    expected: int,
) -> None:
    requested = chat_reply_token_budget(band)  # type: ignore[arg-type]
    resolved = resolve_task_token_budget("llm_chat", tools_enabled=tools_enabled, requested=requested)

    assert requested == expected
    assert resolved == expected
    assert inference_options_from_metadata({"token_count": resolved})["num_predict"] == expected


def test_unknown_chat_reply_budget_band_raises() -> None:
    with pytest.raises(ValueError, match="unknown chat reply budget band"):
        chat_reply_token_budget("verbose")  # type: ignore[arg-type]


def test_chat_explicit_budget_is_capped_at_tool_reply_band() -> None:
    assert resolve_task_token_budget("llm_chat", tools_enabled=True, requested=9999) == 512


@pytest.mark.parametrize("task", ["llm_chat", "drunk"])
def test_tool_reply_budget_requires_tools_enabled(task: str) -> None:
    requested = chat_reply_token_budget("tool")

    assert resolve_task_token_budget(task, tools_enabled=False, requested=requested) == 256
    assert resolve_task_token_budget(task, tools_enabled=True, requested=requested) == 512


def test_semantic_vision_has_separate_complexity_budget() -> None:
    assert task_token_budget("repeater.semantic_style", operation="vision") == 100


def test_unknown_task_token_budget_raises() -> None:
    with pytest.raises(ValueError, match="unknown LLM task budget key"):
        task_token_budget("llm_caht")  # type: ignore[arg-type]


def test_non_chat_explicit_budget_is_preserved_after_task_validation() -> None:
    assert resolve_task_token_budget("memory_extract", tools_enabled=False, requested=192) == 192


def test_unknown_submit_task_does_not_hide_behind_explicit_budget() -> None:
    with pytest.raises(ValueError, match="unknown LLM task budget key"):
        resolve_task_token_budget("memory_extrcat", tools_enabled=False, requested=192)


@pytest.mark.parametrize(
    "relative_path",
    [
        "pallas/product/llm/sticker_vision.py",
        "pallas/product/llm/vision_messages.py",
        "pallas/product/llm/memory/auto_episode.py",
        "pallas/product/llm/memory/graph/extract.py",
        "pallas/product/llm/memory/graph/hiergraph.py",
        "pallas/product/persona/affect_refine_client.py",
        "pallas/product/llm/offline_quality_eval.py",
        "pallas/product/llm/current_turn_decision.py",
        "pallas/product/llm/repeater_semantic_style.py",
    ],
)
def test_internal_llm_jobs_do_not_hardcode_provider_token_budget(relative_path: str) -> None:
    tree = ast.parse(Path(relative_path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            if isinstance(key, ast.Constant) and key.value in {"max_tokens", "num_predict"}:
                assert not isinstance(value, ast.Constant) or not isinstance(value.value, int), relative_path


def test_llm_config_omits_retired_repeater_mode() -> None:
    retired = {
        "llm_repeater_mode",
        "llm_fallback_enabled",
        "llm_polish_enabled",
        "llm_select_enabled",
        "llm_select_max_candidates",
        "llm_polish_lite_enabled",
        "llm_polish_lite_sample_rate",
        "llm_output_filter_polish_lite_hard_phrases",
        "llm_output_filter_polish_lite_soft_phrases",
    }
    assert retired.isdisjoint(LlmConfig.model_fields)
