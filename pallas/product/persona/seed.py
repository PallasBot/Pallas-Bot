"""账号级轻量牛格种子：自动派生 + 手改覆盖，主要拉开选句加权。"""

from __future__ import annotations

import time
from typing import Any

from .auto import archetype_for_bot_id
from .model import ResolvedPersona

SEED_PREF_CHOICES: tuple[str, ...] = ("chaotic", "restrained", "warm")
_MAX_PREFS = 2
_ACCOUNT_PROFILE_PREFS = frozenset(("chaotic", "restrained", "warm"))


def normalize_seed_prefs(raw: object) -> list[str]:
    if not isinstance(raw, list | tuple):
        return []
    out: list[str] = []
    for item in raw:
        pref = str(item or "").strip().lower()
        if pref in SEED_PREF_CHOICES and pref not in out:
            out.append(pref)
        if len(out) >= _MAX_PREFS:
            break
    return out


def derive_auto_seed_prefs(bot_id: int) -> list[str]:
    archetype = archetype_for_bot_id(int(bot_id))
    if archetype == "terse":
        return ["restrained"]
    if archetype == "chaotic":
        return ["chaotic"]
    return ["warm"]


def extract_stored_seed_prefs(persona_dict: dict[str, Any] | None) -> tuple[list[str], str] | None:
    if not isinstance(persona_dict, dict):
        return None
    for key, source in (("seed_override", "manual"), ("seed", "auto")):
        stored = persona_dict.get(key)
        if not isinstance(stored, dict):
            continue
        prefs = normalize_seed_prefs(stored.get("prefs"))
        if any(pref in _ACCOUNT_PROFILE_PREFS for pref in prefs):
            return prefs, source
    return None


def build_auto_seed_payload(bot_id: int) -> dict[str, Any]:
    return {
        "prefs": derive_auto_seed_prefs(bot_id),
        "source": "auto",
        "updated_at": int(time.time()),
    }


def resolve_effective_seed_prefs(
    persona_dict: dict[str, Any] | None,
    bot_id: int,
) -> tuple[list[str], str]:
    if isinstance(persona_dict, dict):
        override = persona_dict.get("seed_override")
        if isinstance(override, dict):
            prefs = normalize_seed_prefs(override.get("prefs"))
            if prefs:
                return prefs, "manual"
        seed = persona_dict.get("seed")
        if isinstance(seed, dict):
            prefs = normalize_seed_prefs(seed.get("prefs"))
            if prefs:
                return prefs, "auto"
    return derive_auto_seed_prefs(bot_id), "auto"


def apply_seed_prefs(persona: ResolvedPersona, prefs: list[str]) -> ResolvedPersona:
    normalized = normalize_seed_prefs(prefs)
    if not normalized:
        return persona
    payload = persona.model_dump()
    for pref in normalized:
        if pref == "chaotic":
            payload["chaos_bias"] = max(float(payload.get("chaos_bias") or 0.0), 0.42)
            payload["assertiveness"] = max(-1.0, min(1.0, float(payload.get("assertiveness") or 0.0) + 0.12))
        elif pref == "restrained":
            payload["chaos_bias"] = min(float(payload.get("chaos_bias") or 0.0), 0.08)
            payload["warmth"] = max(-1.0, min(1.0, float(payload.get("warmth") or 0.0) - 0.1))
            payload["assertiveness"] = max(-1.0, min(1.0, float(payload.get("assertiveness") or 0.0) - 0.08))
        elif pref == "warm":
            payload["warmth"] = max(-1.0, min(1.0, float(payload.get("warmth") or 0.0) + 0.22))
            payload["reply_bias"] = max(0.5, min(2.0, float(payload.get("reply_bias") or 1.0) * 1.06))
    payload["chaos_bias"] = max(0.0, min(1.0, float(payload.get("chaos_bias") or 0.0)))
    return ResolvedPersona(**payload)


def merge_persona_with_seed_patch(
    existing: dict[str, Any] | None,
    patch: dict[str, Any],
    *,
    bot_id: int,
) -> dict[str, Any]:
    """合并 WebUI 种子补丁，保留 cross_group / aliases 等既有字段。"""
    merged: dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}
    if "account_profile" in patch:
        raw_profile = patch.get("account_profile")
        if raw_profile is None:
            merged.pop("account_profile", None)
        elif isinstance(raw_profile, dict):
            from .account_profile import AccountPersonaProfile

            merged["account_profile"] = AccountPersonaProfile.model_validate(raw_profile).model_dump()
    if "seed_override" in patch:
        override = patch.get("seed_override")
        if override is None:
            merged.pop("seed_override", None)
        elif isinstance(override, dict):
            prefs = normalize_seed_prefs(override.get("prefs"))
            if prefs:
                merged["seed_override"] = {
                    "prefs": prefs,
                    "source": "manual",
                    "updated_at": int(time.time()),
                }
            else:
                merged.pop("seed_override", None)
    if "seed" in patch and isinstance(patch.get("seed"), dict):
        prefs = normalize_seed_prefs(patch["seed"].get("prefs"))
        if prefs:
            merged["seed"] = {
                "prefs": prefs,
                "source": "auto",
                "updated_at": int(time.time()),
            }
    if "disposition" in patch:
        raw_disposition = patch.get("disposition")
        if raw_disposition is None:
            merged.pop("disposition", None)
        elif isinstance(raw_disposition, dict):
            from .disposition import resolve_persona_disposition

            disposition = resolve_persona_disposition({"disposition": raw_disposition})
            if any((
                disposition.approach,
                disposition.initiative,
                disposition.conflict,
                disposition.do,
                disposition.dont,
            )):
                merged["disposition"] = disposition.model_dump()
            else:
                merged.pop("disposition", None)
    if "seed" not in merged:
        merged["seed"] = build_auto_seed_payload(bot_id)
    return merged


def ensure_persona_auto_seed(persona: dict[str, Any] | None, bot_id: int) -> dict[str, Any]:
    payload = dict(persona) if isinstance(persona, dict) else {}
    existing = payload.get("seed")
    if isinstance(existing, dict) and normalize_seed_prefs(existing.get("prefs")):
        return payload
    payload["seed"] = build_auto_seed_payload(bot_id)
    return payload
