"""Canonical capability resolution for the repeater LLM pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

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
    llm_enabled = bool(cfg.llm_chat_enabled)
    return RepeaterCapabilities(
        mode="off",
        llm_enabled=llm_enabled,
        fallback_enabled=False,
        polish_enabled=False,
        select_enabled=False,
        polish_lite_enabled=False,
    )
