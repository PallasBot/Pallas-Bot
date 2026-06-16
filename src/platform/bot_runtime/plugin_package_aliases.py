"""历史插件包名 → 现行包名（兼容一个版本周期）。"""

from __future__ import annotations

PLUGIN_PACKAGE_ALIASES: dict[str, str] = {
    "pallas_webui": "pb_webui",
}


def canonical_plugin_package(name: str) -> str:
    key = (name or "").strip()
    if not key:
        return key
    return PLUGIN_PACKAGE_ALIASES.get(key, key)
