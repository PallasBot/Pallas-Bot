"""pb_webui 数据目录；启动时从 pallas_webui 迁移一次。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.foundation.paths import plugin_data_dir

if TYPE_CHECKING:
    from pathlib import Path

_LEGACY_PLUGIN = "pallas_webui"
_CURRENT_PLUGIN = "pb_webui"
_migrated = False


def pb_webui_data_dir(*, create: bool = True) -> Path:
    global _migrated
    if create and not _migrated:
        legacy = plugin_data_dir(_LEGACY_PLUGIN, create=False)
        new_root = plugin_data_dir(_CURRENT_PLUGIN, create=False)
        if legacy.is_dir() and not new_root.exists():
            legacy.rename(new_root)
        _migrated = True
    return plugin_data_dir(_CURRENT_PLUGIN, create=create)
