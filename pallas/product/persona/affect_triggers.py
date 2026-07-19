"""情感 trigger：LLM 提炼短语，热路径子串命中累加偏移。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from .affect_baseline import clamp_affect

if TYPE_CHECKING:
    from .model import ResolvedPersona

_TRIGGER_WEIGHT_DECAY = 0.85
_TRIGGER_WEIGHT_FLOOR = 0.1
_TRIGGER_STORE_CAP = 16
_DEFAULT_TTL_HOURS = 168


def normalize_trigger_entry(raw: dict[str, Any], *, now_ts: int | None = None) -> dict[str, Any] | None:
    phrase = str(raw.get("phrase") or "").strip().lower()
    if not phrase:
        return None
    now = int(now_ts or time.time())
    ttl_hours = int(raw.get("ttl_hours") or _DEFAULT_TTL_HOURS)
    ttl_hours = max(1, min(720, ttl_hours))
    expires_at = int(raw.get("expires_at") or (now + ttl_hours * 3600))
    return {
        "phrase": phrase[:64],
        "warmth_delta": round(clamp_affect(float(raw.get("warmth_delta") or 0.0), lower=-0.5, upper=0.5), 3),
        "assertiveness_delta": round(
            clamp_affect(float(raw.get("assertiveness_delta") or 0.0), lower=-0.5, upper=0.5),
            3,
        ),
        "expires_at": expires_at,
        "weight": round(max(_TRIGGER_WEIGHT_FLOOR, min(1.0, float(raw.get("weight") or 1.0))), 3),
    }


def decay_affect_triggers(triggers: list[dict[str, Any]], *, now_ts: int | None = None) -> list[dict[str, Any]]:
    now = int(now_ts or time.time())
    kept: list[dict[str, Any]] = []
    for item in triggers:
        if not isinstance(item, dict):
            continue
        expires_at = int(item.get("expires_at") or 0)
        if expires_at and expires_at < now:
            continue
        weight = float(item.get("weight") or 1.0) * _TRIGGER_WEIGHT_DECAY
        if weight < _TRIGGER_WEIGHT_FLOOR:
            continue
        kept.append({**item, "weight": round(weight, 3)})
    return kept[:_TRIGGER_STORE_CAP]


def merge_affect_triggers(
    previous: list[dict[str, Any]] | None,
    incoming: list[dict[str, Any]] | None,
    *,
    now_ts: int | None = None,
) -> list[dict[str, Any]]:
    now = int(now_ts or time.time())
    merged = decay_affect_triggers(list(previous or []), now_ts=now)
    if not incoming:
        return merged

    by_phrase: dict[str, dict[str, Any]] = {str(item["phrase"]): item for item in merged if item.get("phrase")}
    for raw in incoming:
        if not isinstance(raw, dict):
            continue
        entry = normalize_trigger_entry(raw, now_ts=now)
        if entry is None:
            continue
        phrase = str(entry["phrase"])
        prev = by_phrase.get(phrase)
        if prev is not None:
            entry["weight"] = round(min(1.0, float(prev.get("weight") or 0.0) + 0.15), 3)
        by_phrase[phrase] = entry

    ordered = sorted(by_phrase.values(), key=lambda item: float(item.get("weight") or 0.0), reverse=True)
    return ordered[:_TRIGGER_STORE_CAP]


def extract_affect_triggers(style_profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(style_profile, dict):
        return []
    sample = style_profile.get("sample")
    if not isinstance(sample, dict):
        return []
    triggers = sample.get("affect_triggers")
    if not isinstance(triggers, list):
        return []
    now = int(time.time())
    return decay_affect_triggers([item for item in triggers if isinstance(item, dict)], now_ts=now)


def scan_affect_trigger_bias(plain_text: str, triggers: list[dict[str, Any]]) -> tuple[float, float]:
    plain = str(plain_text or "").strip().lower()
    if not plain or not triggers:
        return 0.0, 0.0
    warmth = 0.0
    assertiveness = 0.0
    for item in triggers:
        phrase = str(item.get("phrase") or "")
        if not phrase or phrase not in plain:
            continue
        weight = float(item.get("weight") or 1.0)
        warmth += float(item.get("warmth_delta") or 0.0) * weight
        assertiveness += float(item.get("assertiveness_delta") or 0.0) * weight
    return (
        round(clamp_affect(warmth, lower=-0.3, upper=0.3), 3),
        round(clamp_affect(assertiveness, lower=-0.3, upper=0.3), 3),
    )


def apply_affect_trigger_bias(
    persona: ResolvedPersona,
    plain_text: str,
    triggers: list[dict[str, Any]],
) -> ResolvedPersona:
    warmth_delta, assertiveness_delta = scan_affect_trigger_bias(plain_text, triggers)
    if warmth_delta == 0.0 and assertiveness_delta == 0.0:
        return persona
    return persona.model_copy(
        update={
            "warmth": clamp_affect(persona.warmth + warmth_delta),
            "assertiveness": clamp_affect(persona.assertiveness + assertiveness_delta),
        }
    )


def trigger_phrase_weight_multiplier(text: str, triggers: list[dict[str, Any]]) -> float:
    plain = str(text or "").strip().lower()
    if not plain or not triggers:
        return 1.0
    multiplier = 1.0
    for item in triggers:
        phrase = str(item.get("phrase") or "")
        if phrase and phrase in plain:
            weight = float(item.get("weight") or 1.0)
            multiplier *= 1.0 + weight * 0.25
    return max(0.05, multiplier)


def apply_affect_refine_triggers_to_profile(
    profile: dict[str, Any],
    refine: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(profile, dict):
        return profile
    sample = profile.get("sample")
    if not isinstance(sample, dict):
        return profile
    incoming = refine.get("triggers") if isinstance(refine, dict) else None
    if not isinstance(incoming, list) and not isinstance(sample.get("affect_triggers"), list):
        return profile
    sample = dict(sample)
    profile = dict(profile)
    profile["sample"] = sample
    sample["affect_triggers"] = merge_affect_triggers(
        sample.get("affect_triggers") if isinstance(sample.get("affect_triggers"), list) else None,
        incoming if isinstance(incoming, list) else None,
    )
    return profile
