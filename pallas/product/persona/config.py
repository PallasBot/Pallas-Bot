"""Persona 行为层可选开关。"""

from __future__ import annotations

from pallas.core.foundation.config.repo_settings import repo_env_raw_value


def _env_bool(key: str, default: bool) -> bool:
    raw = repo_env_raw_value(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def persona_archetype_enabled() -> bool:
    return _env_bool("PERSONA_ARCHETYPE_ENABLED", True)


def persona_scorer_content_tags_enabled() -> bool:
    return _env_bool("PERSONA_SCORER_CONTENT_TAGS_ENABLED", True)


def persona_affect_gate_enabled() -> bool:
    return _env_bool("PERSONA_AFFECT_GATE_ENABLED", True)


def persona_activity_ingress_enabled() -> bool:
    return _env_bool("PERSONA_ACTIVITY_INGRESS_ENABLED", True)


def persona_preset_layers_enabled() -> bool:
    return _env_bool("PERSONA_PRESET_LAYERS_ENABLED", True)
