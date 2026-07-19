"""中心化插件身份注册表。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pallas.core.platform.bot_runtime.plugin_matrix import (
    CORE_PLUGIN_NAMES,
    EXTRA_PACKAGE_MODULES,
    EXTRA_PLUGIN_PACKAGES,
    PLUGIN_BUNDLED_MODULE_PREFIXES,
    PLUGIN_LEGACY_ALIASES,
    SHARD_INTERNAL_PLUGIN_NAMES,
)

PluginKind = Literal["core", "extra", "shard-internal", "unknown"]


@dataclass(frozen=True, slots=True)
class PluginIdentity:
    plugin_id: str
    kind: PluginKind
    bundled_module_prefix: str | None
    pip_module_prefix: str | None
    pip_package: str | None
    legacy_aliases: tuple[str, ...] = ()


def _infer_pip_module_prefix(plugin_id: str, pip_package: str | None) -> str | None:
    if not pip_package:
        return None
    modules = EXTRA_PACKAGE_MODULES.get(pip_package, ())
    direct = f"pallas_plugin_{plugin_id}"
    if direct in modules:
        return direct
    if plugin_id.startswith("pb_"):
        legacy_pb = f"pallas_plugin_{plugin_id[len('pb_') :]}"
        if legacy_pb in modules:
            return legacy_pb
    return None


def _build_registry() -> dict[str, PluginIdentity]:
    plugin_ids = (
        set(CORE_PLUGIN_NAMES)
        | set(EXTRA_PLUGIN_PACKAGES)
        | set(PLUGIN_BUNDLED_MODULE_PREFIXES)
        | set(PLUGIN_LEGACY_ALIASES)
        | set(SHARD_INTERNAL_PLUGIN_NAMES)
    )
    registry: dict[str, PluginIdentity] = {}
    for plugin_id in sorted(plugin_ids):
        pip_package = EXTRA_PLUGIN_PACKAGES.get(plugin_id)
        if plugin_id in SHARD_INTERNAL_PLUGIN_NAMES:
            kind: PluginKind = "shard-internal"
        elif pip_package:
            kind = "extra"
        else:
            kind = "core"
        registry[plugin_id] = PluginIdentity(
            plugin_id=plugin_id,
            kind=kind,
            bundled_module_prefix=PLUGIN_BUNDLED_MODULE_PREFIXES.get(plugin_id),
            pip_module_prefix=_infer_pip_module_prefix(plugin_id, pip_package),
            pip_package=pip_package,
            legacy_aliases=PLUGIN_LEGACY_ALIASES.get(plugin_id, ()),
        )
    return registry


_REGISTRY: dict[str, PluginIdentity] = _build_registry()

_ALIASES: dict[str, str] = {}
_MODULE_PREFIXES: list[tuple[str, str]] = []

for plugin_id, ident in _REGISTRY.items():
    _ALIASES[plugin_id] = plugin_id
    for alias in ident.legacy_aliases:
        _ALIASES[alias] = plugin_id
    if ident.bundled_module_prefix:
        _MODULE_PREFIXES.append((ident.bundled_module_prefix, plugin_id))
    if ident.pip_module_prefix:
        _MODULE_PREFIXES.append((ident.pip_module_prefix, plugin_id))

_MODULE_PREFIXES.sort(key=lambda item: len(item[0]), reverse=True)


def canonical_plugin_id(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return text
    if text in _ALIASES:
        return _ALIASES[text]
    for prefix, plugin_id in _MODULE_PREFIXES:
        if text == prefix or text.startswith(f"{prefix}."):
            return plugin_id
    short = text.rsplit(".", 1)[-1]
    return _ALIASES.get(short, short)


def plugin_identity(raw: str) -> PluginIdentity:
    plugin_id = canonical_plugin_id(raw)
    ident = _REGISTRY.get(plugin_id)
    if ident is None:
        raise KeyError(plugin_id)
    return ident


def plugin_identity_from_module(module_name: str) -> PluginIdentity:
    return plugin_identity(module_name)
