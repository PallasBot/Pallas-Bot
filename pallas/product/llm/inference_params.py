"""由群风格画像派生温度与句长预算。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pallas.product.persona.model import ResolvedPersona

_BASE_TEMPERATURE = 0.55
_LENGTH_TOKEN_MAP: dict[str, int] = {
    "short": 128,
    "medium": 240,
    "long": 360,
    "any": 240,
}
# 带 tool 查证时需列出数据并口语化总结，短于该值易在句中硬截断。
_CHAT_TOOLS_TOKEN_FLOOR = 280


def derive_llm_inference_params(
    persona: ResolvedPersona,
    *,
    mode: str = "normal",
    purpose: str = "chat",
) -> tuple[float | None, int | None]:
    """返回温度与句长上限；醉酒模式不传温度。"""
    if str(mode or "normal").strip().lower() == "drunk":
        return None, token_count_for_persona(persona, purpose=purpose)

    if purpose == "select":
        return 0.28, token_count_for_persona(persona, purpose=purpose)

    if purpose == "polish_lite":
        return 0.35, token_count_for_persona(persona, purpose=purpose)

    if purpose == "fallback_lite":
        return 0.42, token_count_for_persona(persona, purpose=purpose)

    temperature = _BASE_TEMPERATURE
    temperature += float(persona.chaos_bias) * 0.25
    temperature += max(0.0, float(persona.warmth)) * 0.08
    temperature += max(0.0, float(persona.assertiveness)) * 0.06
    temperature += max(0.0, float(persona.bluntness)) * 0.05
    temperature -= max(0.0, -float(persona.warmth)) * 0.05
    temperature -= max(0.0, -float(persona.bluntness)) * 0.03
    temperature = max(0.2, min(1.1, temperature))
    return temperature, token_count_for_persona(persona, purpose=purpose)


def token_count_for_persona(persona: ResolvedPersona, *, purpose: str = "chat") -> int:
    length_pref = str(persona.length_pref or "any").strip().lower()
    base = _LENGTH_TOKEN_MAP.get(length_pref, _LENGTH_TOKEN_MAP["any"])
    if purpose == "polish":
        return min(base, 96)
    if purpose == "select":
        return 48
    if purpose == "polish_lite":
        return 80
    if purpose == "fallback_lite":
        return min(base, 128)
    if purpose == "fallback":
        return min(base, 160)
    return base


def chat_token_count_with_tools(token_count: int | None, *, tools_enabled: bool) -> int | None:
    if token_count is None:
        return _CHAT_TOOLS_TOKEN_FLOOR if tools_enabled else None
    if tools_enabled:
        return max(int(token_count), _CHAT_TOOLS_TOKEN_FLOOR)
    return int(token_count)
