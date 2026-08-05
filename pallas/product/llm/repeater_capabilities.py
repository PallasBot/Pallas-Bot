"""Canonical capability resolution for the repeater LLM pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from .config import resolve_llm_repeater_flags, resolve_llm_repeater_mode

if TYPE_CHECKING:
    from .config import LLMConfig


RepeaterMode = Literal["off", "select"]


@dataclass(frozen=True)
class RepeaterCapabilities:
    mode: RepeaterMode
    llm_enabled: bool
    fallback_enabled: bool
    polish_enabled: bool
    select_enabled: bool
    polish_lite_enabled: bool


def resolve_repeater_capabilities(cfg: LLMConfig) -> RepeaterCapabilities:
    configured_mode = str(getattr(cfg, "llm_repeater_mode", "") or "").strip().lower()
    if configured_mode:
        legacy_mode = configured_mode
        fallback_enabled = bool(getattr(cfg, "llm_fallback_enabled", False))
        polish_enabled = bool(getattr(cfg, "llm_polish_enabled", False))
        select_enabled = bool(getattr(cfg, "llm_select_enabled", False))
    else:
        legacy_mode = resolve_llm_repeater_mode()
        fallback_enabled, polish_enabled, select_enabled = resolve_llm_repeater_flags()
    mode: RepeaterMode = "off" if legacy_mode == "off" else "select"

    if mode == "off":
        fallback_enabled = polish_enabled = select_enabled = False
    else:
        fallback_enabled, polish_enabled, select_enabled = False, False, True

    llm_enabled = bool(cfg.llm_chat_enabled)
    return RepeaterCapabilities(
        mode=mode,
        llm_enabled=llm_enabled,
        fallback_enabled=llm_enabled and fallback_enabled,
        polish_enabled=llm_enabled and polish_enabled,
        select_enabled=llm_enabled and select_enabled,
        polish_lite_enabled=False,
    )
