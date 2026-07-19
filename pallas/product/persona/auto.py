from .model import ArchetypeName, LengthPref, ResolvedPersona, Tone

_TONES: tuple[Tone, ...] = ("neutral", "calm", "enthusiastic", "dramatic", "terse")
_LENGTH_PREFS: tuple[LengthPref, ...] = ("any", "short", "medium", "long")
_ARCHETYPE_NAMES: tuple[ArchetypeName, ...] = ("terse", "chaotic", "polite")

_ARCHETYPE_LABELS: dict[str, str] = {
    "terse": "寡言",
    "chaotic": "混沌",
    "polite": "礼貌",
}

_ARCHETYPE_OVERLAYS: dict[str, dict[str, float | str]] = {
    "terse": {
        "tone": "terse",
        "length_pref": "short",
        "chaos_bias": 0.08,
        "warmth": -0.12,
        "assertiveness": 0.05,
    },
    "chaotic": {
        "tone": "dramatic",
        "length_pref": "short",
        "chaos_bias": 0.55,
        "warmth": 0.05,
        "assertiveness": 0.18,
    },
    "polite": {
        "tone": "calm",
        "length_pref": "medium",
        "chaos_bias": 0.05,
        "warmth": 0.22,
        "assertiveness": -0.12,
    },
}


def archetype_for_bot_id(bot_id: int) -> ArchetypeName:
    return _ARCHETYPE_NAMES[int(bot_id) % len(_ARCHETYPE_NAMES)]


def derive_persona_from_bot_id(bot_id: int, *, archetype_enabled: bool = True) -> ResolvedPersona:
    bid = int(bot_id)
    persona = ResolvedPersona(
        source="auto",
        preset_label="自动",
        tone=_TONES[bid % len(_TONES)],
        reply_bias=round(0.85 + (bid % 7) * 0.05, 2),
        speak_bias=round(0.90 + (bid % 5) * 0.04, 2),
        length_pref=_LENGTH_PREFS[bid % len(_LENGTH_PREFS)],
        warmth=round(((bid % 7) - 3) * 0.08, 2),
        assertiveness=round(((bid % 11) - 5) * 0.06, 2),
    )
    if not archetype_enabled:
        return persona

    archetype = archetype_for_bot_id(bid)
    overlay = _ARCHETYPE_OVERLAYS.get(archetype)
    if not overlay:
        return persona

    payload = persona.model_dump()
    payload["archetype"] = archetype
    payload["preset_label"] = _ARCHETYPE_LABELS.get(archetype, archetype)
    for key, value in overlay.items():
        if key in ("tone", "length_pref"):
            payload[key] = value
        elif isinstance(value, int | float):
            if key == "chaos_bias":
                payload[key] = max(0.0, min(1.0, float(value)))
            elif key in ("warmth", "assertiveness"):
                payload[key] = max(-1.0, min(1.0, float(payload.get(key, 0.0)) + float(value)))
            else:
                payload[key] = float(value)
    return ResolvedPersona(**payload)
