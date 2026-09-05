"""插件身份解析：模块短名与规范化插件 ID。"""

from __future__ import annotations

from pallas.core.platform.plugin_runtime.plugin_identity import canonical_plugin_id


def _module_short_name(module_path: str) -> str:
    return (module_path or "").rsplit(".", 1)[-1]


def resolved_plugin_identity(raw_name: str, module_name: str = "") -> str:
    for candidate in (raw_name, module_name, _module_short_name(module_name)):
        resolved = canonical_plugin_id((candidate or "").strip())
        if resolved:
            return resolved
    return (raw_name or "").strip()
