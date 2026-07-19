"""Persona 情感观测：供控制台 WebUI 只读展示。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pallas.core.foundation.db import make_group_config_repository

from .affect_axes import assertiveness_behavior_hint, bluntness_behavior_hint, warmth_behavior_hint
from .affect_triggers import extract_affect_triggers
from .compile_group_style import compile_group_style_snapshot
from .loader import resolve_persona

if TYPE_CHECKING:
    from .model import ResolvedPersona


def persona_axis_snapshot(persona: ResolvedPersona) -> dict[str, Any]:
    return {
        "source": str(persona.source or ""),
        "preset_label": str(persona.preset_label or ""),
        "archetype": str(persona.archetype or ""),
        "tone": str(persona.tone or ""),
        "reply_bias": float(persona.reply_bias),
        "speak_bias": float(persona.speak_bias),
        "length_pref": str(persona.length_pref or ""),
        "chaos_bias": float(persona.chaos_bias),
        "warmth": float(persona.warmth),
        "assertiveness": float(persona.assertiveness),
        "bluntness": float(persona.bluntness),
        "harsh_msg_ratio": float(persona.harsh_msg_ratio),
        "polite_msg_ratio": float(persona.polite_msg_ratio),
        "msgs_per_hour_active": float(persona.msgs_per_hour_active),
        "activity_level": str(persona.activity_level or ""),
    }


def behavior_hint_lines(persona: ResolvedPersona) -> list[str]:
    lines: list[str] = []
    for hint in (
        warmth_behavior_hint(float(persona.warmth)),
        assertiveness_behavior_hint(float(persona.assertiveness)),
        bluntness_behavior_hint(float(persona.bluntness)),
    ):
        text = str(hint or "").strip().lstrip("-").strip()
        if text:
            lines.append(text)
    return lines


def parse_observe_accounts(raw: str | None) -> list[int] | None:
    if raw is None or not str(raw).strip():
        return None
    out: list[int] = []
    for part in str(raw).split(","):
        piece = part.strip()
        if not piece:
            continue
        try:
            account = int(piece)
        except ValueError:
            continue
        if account > 0 and account not in out:
            out.append(account)
    return out or None


def affect_refine_snapshot(style_profile: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(style_profile, dict):
        return None
    sample = style_profile.get("sample")
    if not isinstance(sample, dict):
        return None
    refine = sample.get("affect_refine")
    if not isinstance(refine, dict):
        return None
    return {
        "source": str(refine.get("source") or "none"),
        "warmth_delta": float(refine.get("warmth_delta") or 0.0),
        "assertiveness_delta": float(refine.get("assertiveness_delta") or 0.0),
        "confidence": float(refine.get("confidence") or 0.0),
        "summary": str(refine.get("summary") or "")[:256],
        "updated_at": refine.get("updated_at"),
    }


def affect_triggers_snapshot(style_profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    triggers = extract_affect_triggers(style_profile if isinstance(style_profile, dict) else None)
    rows: list[dict[str, Any]] = []
    for item in triggers:
        if not isinstance(item, dict):
            continue
        phrase = str(item.get("phrase") or "").strip()
        if not phrase:
            continue
        rows.append({
            "phrase": phrase,
            "warmth_delta": float(item.get("warmth_delta") or 0.0),
            "assertiveness_delta": float(item.get("assertiveness_delta") or 0.0),
            "weight": float(item.get("weight") or 0.0),
            "expires_at": item.get("expires_at"),
        })
    return rows


async def build_persona_observe_payload(
    *,
    group_id: int | None = None,
    accounts: list[int] | None = None,
) -> dict[str, Any]:
    from pallas.core.foundation.db.pallas_console_data import list_all_bot_configs_public

    bot_rows = await list_all_bot_configs_public()
    if accounts:
        wanted = {int(a) for a in accounts}
        bot_rows = [row for row in bot_rows if int(row.get("account") or 0) in wanted]

    gid = int(group_id) if group_id is not None and int(group_id) > 0 else None
    style_profile: dict[str, Any] | None = None
    group_snapshot: dict[str, Any] | None = None

    if gid is not None:
        repo = make_group_config_repository()
        group_config = await repo.get(gid)
        raw_profile = getattr(group_config, "style_profile", None) if group_config is not None else None
        if isinstance(raw_profile, dict):
            style_profile = raw_profile
        group_snapshot = compile_group_style_snapshot(style_profile)

    bots: list[dict[str, Any]] = []
    for row in bot_rows:
        account = int(row.get("account") or 0)
        if account <= 0:
            continue
        group_style_enabled = bool(row.get("group_style_enabled", True))
        base_persona = await resolve_persona(account, None)
        resolved_persona = await resolve_persona(account, gid) if gid is not None and group_style_enabled else None
        from pallas.product.persona.seed import resolve_effective_seed_prefs

        raw_persona = row.get("persona") if isinstance(row.get("persona"), dict) else None
        seed_prefs, seed_source = resolve_effective_seed_prefs(
            raw_persona if isinstance(raw_persona, dict) else None,
            account,
        )
        entry: dict[str, Any] = {
            "account": account,
            "group_style_enabled": group_style_enabled,
            "seed_prefs": seed_prefs,
            "seed_source": seed_source,
            "base": persona_axis_snapshot(base_persona),
            "base_hints": behavior_hint_lines(base_persona),
        }
        if resolved_persona is not None:
            entry["resolved"] = persona_axis_snapshot(resolved_persona)
            entry["resolved_hints"] = behavior_hint_lines(resolved_persona)
        else:
            entry["resolved"] = None
            entry["resolved_hints"] = []
        bots.append(entry)

    bots.sort(key=lambda item: int(item.get("account") or 0))

    return {
        "group_id": gid,
        "group_style_snapshot": group_snapshot,
        "affect_refine": affect_refine_snapshot(style_profile),
        "affect_triggers": affect_triggers_snapshot(style_profile),
        "bots": bots,
    }
