"""插件名别名。"""

from __future__ import annotations

from pallas.core.platform.plugin_runtime.plugin_identity import canonical_plugin_id

PLUGIN_LEGACY_NAMES: dict[str, str] = {
    "ollama": "llm_chat",
    "community_stats": "pb_stats",
}


def canonical_plugin_name(name: str) -> str:
    key = (name or "").strip()
    if not key:
        return key
    return PLUGIN_LEGACY_NAMES.get(key, key)


def plugin_name_aliases(name: str) -> frozenset[str]:
    raw = (name or "").strip()
    canonical = canonical_plugin_name(raw)
    names = {canonical}
    resolved = canonical_plugin_id(raw)
    if resolved:
        names.add(resolved)
    for legacy, current in PLUGIN_LEGACY_NAMES.items():
        if current == canonical:
            names.add(legacy)
    if name.strip():
        names.add(name.strip())
    return frozenset(names)


def is_plugin_name_in_set(name: str, names: frozenset[str] | set[str]) -> bool:
    canonical_names = {canonical_plugin_id(str(item).strip()) for item in names if str(item).strip()}
    return bool(plugin_name_aliases(name) & canonical_names)


def expand_disabled_plugin_names(names: frozenset[str] | set[str]) -> frozenset[str]:
    expanded: set[str] = set()
    for name in names:
        expanded.update(plugin_name_aliases(name))
    return frozenset(expanded)
