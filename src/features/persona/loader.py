import time

from src.foundation.db import make_bot_config_repository, make_group_config_repository

from .affect_baseline import apply_affect_derived
from .auto import derive_persona_from_bot_id
from .model import ResolvedPersona

_CACHE_TTL_SEC = 60.0
_cache: dict[tuple[int, int | None], tuple[float, ResolvedPersona]] = {}


def invalidate_persona_cache(bot_id: int | None = None) -> None:
    if bot_id is None:
        _cache.clear()
        return
    bid = int(bot_id)
    stale_keys = [key for key in _cache if key[0] == bid]
    for key in stale_keys:
        _cache.pop(key, None)


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

    resolved = derive_persona_from_bot_id(bid)
    bot_repo = make_bot_config_repository()
    bot_config = await bot_repo.get(bid)
    if bot_config is not None:
        resolved = _apply_cross_group_persona(resolved, getattr(bot_config, "persona", None))
        group_style_enabled = bool(getattr(bot_config, "group_style_enabled", True))
    else:
        group_style_enabled = True

    if gid is not None and group_style_enabled:
        repo = make_group_config_repository()
        group_config = await repo.get(gid)
        style_profile = getattr(group_config, "style_profile", None) if group_config is not None else None
        resolved = _apply_group_style_profile(resolved, style_profile)

    _cache[cache_key] = (now, resolved)
    return resolved
