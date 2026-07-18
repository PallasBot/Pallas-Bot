import time

from pallas.core.foundation.db import make_bot_config_repository, make_group_config_repository

from .activity_ingress import (
    activity_reply_bias_multiplier,
    activity_speak_bias_multiplier,
    classify_activity_level,
)
from .affect_axes import derive_bluntness
from .affect_baseline import apply_affect_derived
from .affect_triggers import apply_affect_trigger_bias, extract_affect_triggers
from .auto import derive_persona_from_bot_id
from .config import persona_activity_ingress_enabled, persona_archetype_enabled
from .model import ResolvedPersona

_CACHE_TTL_SEC = 60.0
_cache: dict[tuple[int, int | None], tuple[float, ResolvedPersona]] = {}
_trigger_cache: dict[int, tuple[float, list[dict]]] = {}


def invalidate_persona_cache(bot_id: int | None = None) -> None:
    if bot_id is None:
        _cache.clear()
        _trigger_cache.clear()
        return
    bid = int(bot_id)
    stale_keys = [key for key in _cache if key[0] == bid]
    for key in stale_keys:
        _cache.pop(key, None)
    _trigger_cache.clear()


async def load_affect_triggers(group_id: int) -> list[dict]:
    gid = int(group_id)
    now = time.time()
    cached = _trigger_cache.get(gid)
    if cached is not None and now - cached[0] < _CACHE_TTL_SEC:
        return cached[1]

    repo = make_group_config_repository()
    group_config = await repo.get(gid)
    style_profile = getattr(group_config, "style_profile", None) if group_config is not None else None
    triggers = extract_affect_triggers(style_profile if isinstance(style_profile, dict) else None)
    _trigger_cache[gid] = (now, triggers)
    return triggers


async def resolve_persona_for_message(bot_id: int, group_id: int, plain_text: str) -> ResolvedPersona:
    persona = await resolve_persona(bot_id, group_id)
    triggers = await load_affect_triggers(group_id)
    return apply_affect_trigger_bias(persona, plain_text, triggers)


def _apply_group_style_profile(base: ResolvedPersona, style_profile: dict | None) -> ResolvedPersona:
    if not isinstance(style_profile, dict):
        return base
    derived = style_profile.get("derived")
    if not isinstance(derived, dict):
        return base

    payload = base.model_dump()
    reply_mul = derived.get("reply_bias_mul")
    speak_mul = derived.get("speak_bias_mul")
    if isinstance(reply_mul, int | float):
        payload["reply_bias"] = max(0.5, min(2.0, float(payload["reply_bias"]) * float(reply_mul)))
    if isinstance(speak_mul, int | float):
        payload["speak_bias"] = max(0.5, min(2.0, float(payload["speak_bias"]) * float(speak_mul)))

    length_pref = str(derived.get("length_pref") or "").strip()
    if length_pref:
        payload["length_pref"] = length_pref

    chaos_bias = derived.get("chaos_bias")
    if isinstance(chaos_bias, int | float):
        payload["chaos_bias"] = max(0.0, min(1.0, float(chaos_bias)))

    warmth, assertiveness = apply_affect_derived(
        float(payload.get("warmth") or 0.0),
        float(payload.get("assertiveness") or 0.0),
        derived,
    )
    payload["warmth"] = warmth
    payload["assertiveness"] = assertiveness

    raw = style_profile.get("raw")
    punct_aggression_avg = 0.0
    msgs_per_hour_active = 0.0
    if isinstance(raw, dict):
        msgs_per_hour = raw.get("msgs_per_hour_active")
        if isinstance(msgs_per_hour, int | float):
            msgs_per_hour_active = max(0.0, float(msgs_per_hour))
        affect_tone = raw.get("affect_tone")
        if isinstance(affect_tone, dict):
            harsh_ratio = affect_tone.get("harsh_msg_ratio")
            polite_ratio = affect_tone.get("polite_msg_ratio")
            punct_avg = affect_tone.get("punct_aggression_avg")
            if isinstance(harsh_ratio, int | float):
                payload["harsh_msg_ratio"] = max(0.0, min(1.0, float(harsh_ratio)))
            if isinstance(polite_ratio, int | float):
                payload["polite_msg_ratio"] = max(0.0, min(1.0, float(polite_ratio)))
            if isinstance(punct_avg, int | float):
                punct_aggression_avg = max(0.0, min(1.0, float(punct_avg)))

    payload["bluntness"] = derive_bluntness(
        assertiveness=float(payload.get("assertiveness") or 0.0),
        harsh_msg_ratio=float(payload.get("harsh_msg_ratio") or 0.0),
        polite_msg_ratio=float(payload.get("polite_msg_ratio") or 0.0),
        punct_aggression_avg=punct_aggression_avg,
    )
    payload["msgs_per_hour_active"] = msgs_per_hour_active
    if persona_activity_ingress_enabled():
        level = classify_activity_level(msgs_per_hour_active)
        payload["activity_level"] = level
        payload["reply_bias"] = max(
            0.5,
            min(2.0, float(payload["reply_bias"]) * activity_reply_bias_multiplier(level)),
        )
        payload["speak_bias"] = max(
            0.5,
            min(2.0, float(payload["speak_bias"]) * activity_speak_bias_multiplier(level)),
        )

    return ResolvedPersona(**payload)


def _apply_cross_group_persona(base: ResolvedPersona, persona: dict | None) -> ResolvedPersona:
    if not isinstance(persona, dict) or str(persona.get("source") or "") != "cross_group":
        return base
    return _apply_group_style_profile(base, persona)


async def resolve_persona(bot_id: int, group_id: int | None = None) -> ResolvedPersona:
    """解析接话行为参数。支持 bot 自动派生、跨群汇总与 group 风格画像合并。"""
    bid = int(bot_id)
    gid = int(group_id) if group_id is not None else None
    now = time.time()
    cache_key = (bid, gid)
    cached = _cache.get(cache_key)
    if cached is not None and now - cached[0] < _CACHE_TTL_SEC:
        return cached[1]

    from .seed import apply_seed_prefs, resolve_effective_seed_prefs

    resolved = derive_persona_from_bot_id(bid, archetype_enabled=persona_archetype_enabled())
    bot_repo = make_bot_config_repository()
    bot_config = await bot_repo.get(bid)
    persona_dict = getattr(bot_config, "persona", None) if bot_config is not None else None
    if bot_config is not None:
        resolved = _apply_cross_group_persona(resolved, persona_dict)
        group_style_enabled = bool(getattr(bot_config, "group_style_enabled", True))
    else:
        group_style_enabled = True

    if gid is not None and group_style_enabled:
        repo = make_group_config_repository()
        group_config = await repo.get(gid)
        style_profile = getattr(group_config, "style_profile", None) if group_config is not None else None
        resolved = _apply_group_style_profile(resolved, style_profile)

    # 账号种子最后叠加，避免群画像把多牛差异抹平
    seed_prefs, _seed_source = resolve_effective_seed_prefs(
        persona_dict if isinstance(persona_dict, dict) else None,
        bid,
    )
    resolved = apply_seed_prefs(resolved, seed_prefs)

    _cache[cache_key] = (now, resolved)
    return resolved
