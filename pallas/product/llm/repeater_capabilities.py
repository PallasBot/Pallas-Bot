"""Canonical capability resolution for the repeater LLM pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from .config import resolve_llm_repeater_flags, resolve_llm_repeater_mode

if TYPE_CHECKING:
    from .config import LLMConfig


RepeaterMode = Literal["off", "select", "select_polish_lite", "select_fallback", "fallback"]


@dataclass(frozen=True)
class RepeaterCapabilities:
    mode: RepeaterMode
    llm_enabled: bool
    fallback_enabled: bool
    polish_enabled: bool
    select_enabled: bool
    polish_lite_enabled: bool


def resolve_repeater_capabilities(cfg: LLMConfig) -> RepeaterCapabilities:
    legacy_mode = resolve_llm_repeater_mode()
    fallback_enabled, polish_enabled, select_enabled = resolve_llm_repeater_flags()
    canonical_modes = {"off", "select", "select_polish_lite", "select_fallback", "fallback"}
    mode: RepeaterMode = {
        "polish": "select_polish_lite",
        "both": "select_fallback",
    }.get(legacy_mode, legacy_mode if legacy_mode in canonical_modes else "select")

    if mode == "off":
        fallback_enabled = polish_enabled = select_enabled = False
    elif mode == "fallback":
        fallback_enabled, polish_enabled, select_enabled = True, False, False
    elif mode == "select":
        fallback_enabled, polish_enabled, select_enabled = False, False, True
    elif mode == "select_polish_lite":
        fallback_enabled, polish_enabled, select_enabled = False, False, True
    elif mode == "select_fallback":
        fallback_enabled, polish_enabled, select_enabled = True, False, True

    llm_enabled = bool(cfg.llm_chat_enabled)
    return RepeaterCapabilities(
        mode=mode,
        llm_enabled=llm_enabled,
        fallback_enabled=llm_enabled and fallback_enabled,
        polish_enabled=llm_enabled and polish_enabled,
        select_enabled=llm_enabled and select_enabled,
        polish_lite_enabled=llm_enabled and mode == "select_polish_lite",
    )
