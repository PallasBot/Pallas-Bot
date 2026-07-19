"""部署级（data/<plugin>/plugin_storage.json）同步读写。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pallas.core.foundation.paths import plugin_data_dir

if TYPE_CHECKING:
    from pathlib import Path


def deploy_storage_path(plugin_name: str) -> Path:
    return plugin_data_dir(plugin_name.strip()) / "plugin_storage.json"


def read_deploy_plugin_blob(plugin_name: str) -> dict[str, Any]:
    path = deploy_storage_path(plugin_name)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def write_deploy_plugin_blob(plugin_name: str, blob: dict[str, Any]) -> None:
    path = deploy_storage_path(plugin_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


class DeployPluginStorage:
    """声明式 deploy 作用域存储（同步，供线程热路径使用）。"""

    def __init__(self, plugin_name: str) -> None:
        self.plugin_name = plugin_name.strip()

    def get(self, key: str) -> Any:
        from pallas.core.storage.store import resolve_decl

        resolve_decl(self.plugin_name, key)
        blob = read_deploy_plugin_blob(self.plugin_name)
        return blob.get(key.strip())

    def set(self, key: str, value: Any) -> None:
        from pallas.core.storage.store import resolve_decl

        resolve_decl(self.plugin_name, key)
        blob = read_deploy_plugin_blob(self.plugin_name)
        key_name = key.strip()
        if value is None:
            blob.pop(key_name, None)
        else:
            blob[key_name] = value
        write_deploy_plugin_blob(self.plugin_name, blob)

    def delete(self, key: str) -> None:
        self.set(key, None)
