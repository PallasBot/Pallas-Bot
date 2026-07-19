"""pb_webui 数据目录；启动时从 pallas_webui 迁移一次。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pallas.core.foundation.paths import plugin_data_dir

if TYPE_CHECKING:
    from pathlib import Path

_LEGACY_PLUGIN = "pallas_webui"
_CURRENT_PLUGIN = "pb_webui"
_migrated = False


def migrate_pb_webui_data_dir_if_needed() -> None:
    global _migrated
    if _migrated:
        return
    _migrated = True
    legacy = plugin_data_dir(_LEGACY_PLUGIN, create=False)
    new_root = plugin_data_dir(_CURRENT_PLUGIN, create=False)
    if not legacy.is_dir() or new_root.exists():
        return
    try:
        legacy.rename(new_root)
    except (FileNotFoundError, OSError):
        if new_root.exists() or not legacy.is_dir():
            return
        raise


def pb_webui_data_dir(*, create: bool = True) -> Path:
    migrate_pb_webui_data_dir_if_needed()
    return plugin_data_dir(_CURRENT_PLUGIN, create=create)
