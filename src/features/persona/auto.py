from .model import LengthPref, ResolvedPersona, Tone

_TONES: tuple[Tone, ...] = ("neutral", "calm", "enthusiastic", "dramatic", "terse")
_LENGTH_PREFS: tuple[LengthPref, ...] = ("any", "short", "medium", "long")


def derive_persona_from_bot_id(bot_id: int) -> ResolvedPersona:
    bid = int(bot_id)
    return ResolvedPersona(
        source="auto",
        preset_label="自动",
        tone=_TONES[bid % len(_TONES)],
        reply_bias=round(0.85 + (bid % 7) * 0.05, 2),
        speak_bias=round(0.90 + (bid % 5) * 0.04, 2),
        length_pref=_LENGTH_PREFS[bid % len(_LENGTH_PREFS)],
        warmth=round(((bid % 7) - 3) * 0.08, 2),
        assertiveness=round(((bid % 11) - 5) * 0.06, 2),
    )
