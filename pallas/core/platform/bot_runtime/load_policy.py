"""插件加载 skip：角色名单 + 全局禁用 + 包名别名。"""

from __future__ import annotations


def _expand_plugin_skip_names(names: frozenset[str]) -> frozenset[str]:
    from pallas.core.platform.bot_runtime.plugin_package_aliases import canonical_plugin_package

    out: set[str] = set()
    for name in names:
        key = (name or "").strip()
        if not key:
            continue
        out.add(key)
        canonical = canonical_plugin_package(key)
        if canonical:
            out.add(canonical)
    return frozenset(out)


def merge_startup_skip_plugins(base: frozenset[str]) -> frozenset[str]:
    """合并角色 skip 与全局禁用插件名。"""
    try:
        from pallas.core.platform.bot_runtime.startup_global_disable import startup_global_disabled_plugin_names

        disabled = startup_global_disabled_plugin_names()
        if disabled:
            return _expand_plugin_skip_names(base | disabled)
    except Exception:
        pass
    return _expand_plugin_skip_names(base)
