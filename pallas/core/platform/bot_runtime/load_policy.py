"""插件加载 skip：角色名单 + 全局禁用 + 包名别名。"""

from __future__ import annotations


def _expand_plugin_skip_names(
    names: frozenset[str],
    *,
    include_extra_modules: bool = False,
) -> frozenset[str]:
    from pallas.core.platform.bot_runtime.plugin_matrix import EXTRA_PACKAGE_MODULES
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
        if not include_extra_modules:
            continue
        out.update(module_name.rsplit(".", 1)[-1] for module_name in EXTRA_PACKAGE_MODULES.get(key, ()))
        if canonical:
            from pallas.core.platform.plugin_runtime.plugin_identity import plugin_identity

            try:
                identity = plugin_identity(canonical)
            except KeyError:
                identity = None
            if identity and identity.pip_module_prefix:
                out.add(identity.pip_module_prefix.rsplit(".", 1)[-1])
    return frozenset(out)


def merge_startup_skip_plugins(base: frozenset[str]) -> frozenset[str]:
    """合并角色 skip 与全局禁用插件名。"""
    expanded_base = _expand_plugin_skip_names(base)
    try:
        from pallas.core.platform.bot_runtime.startup_global_disable import startup_global_disabled_plugin_names

        disabled = startup_global_disabled_plugin_names()
        if disabled:
            return expanded_base | _expand_plugin_skip_names(disabled, include_extra_modules=True)
    except Exception:
        pass
    return expanded_base
