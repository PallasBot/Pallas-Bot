"""由群风格画像派生温度与句长预算。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.features.persona.model import ResolvedPersona

_BASE_TEMPERATURE = 0.55
_LENGTH_TOKEN_MAP: dict[str, int] = {
    "short": 80,
    "medium": 120,
    "long": 180,
    "any": 120,
}


def derive_llm_inference_params(
    persona: ResolvedPersona,
    *,
    mode: str = "normal",
    purpose: str = "chat",
) -> tuple[float | None, int | None]:
    """返回温度与句长上限；醉酒模式不传温度。"""
    if str(mode or "normal").strip().lower() == "drunk":
        return None, token_count_for_persona(persona, purpose=purpose)

    temperature = _BASE_TEMPERATURE
    temperature += float(persona.chaos_bias) * 0.25
    temperature += max(0.0, float(persona.warmth)) * 0.08
    temperature += max(0.0, float(persona.assertiveness)) * 0.06
    temperature -= max(0.0, -float(persona.warmth)) * 0.05
    temperature = max(0.2, min(1.1, temperature))
    return temperature, token_count_for_persona(persona, purpose=purpose)


def token_count_for_persona(persona: ResolvedPersona, *, purpose: str = "chat") -> int:
    length_pref = str(persona.length_pref or "any").strip().lower()
    base = _LENGTH_TOKEN_MAP.get(length_pref, _LENGTH_TOKEN_MAP["any"])
    if purpose == "polish":
        return min(base, 96)
    if purpose == "fallback":
        return min(base, 160)
    return base
