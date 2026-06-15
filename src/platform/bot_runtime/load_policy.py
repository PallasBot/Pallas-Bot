"""插件加载跳过策略：角色名单 + 全局禁用。"""

from __future__ import annotations


def merge_startup_skip_plugins(base: frozenset[str]) -> frozenset[str]:
    """合并角色 skip 与全局禁用插件名。"""
    try:
        from src.platform.bot_runtime.startup_global_disable import startup_global_disabled_plugin_names

        disabled = startup_global_disabled_plugin_names()
        if disabled:
            return base | disabled
    except Exception:
        pass
    return base
