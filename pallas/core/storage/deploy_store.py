"""部署级（data/<plugin>/plugin_storage.json）同步读写。"""

from __future__ import annotations

import json
import os
import socket
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from pallas.core.foundation.paths import plugin_data_dir

if TYPE_CHECKING:
    from pathlib import Path


def deploy_storage_path(plugin_name: str) -> Path:
    return plugin_data_dir(plugin_name.strip()) / "plugin_storage.json"


def deploy_storage_audit_path(plugin_name: str) -> Path:
    return plugin_data_dir(plugin_name.strip()) / "plugin_storage.audit.jsonl"


@contextmanager
def _storage_lock(plugin_name: str):
    import fcntl

    path = deploy_storage_path(plugin_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + ".lock").open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _audit_storage_change(plugin_name: str, key: str, old: Any, new: Any) -> None:
    if old == new:
        return
    path = deploy_storage_audit_path(plugin_name)
    entry = {
        "time": time.time(),
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "plugin": plugin_name,
        "key": key,
        "old": old,
        "new": new,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")


def _write_key_locked(plugin_name: str, key: str, value: Any, expected: Any = ...) -> tuple[bool, Any]:
    with _storage_lock(plugin_name):
        blob = read_deploy_plugin_blob(plugin_name)
        old = blob.get(key)
        if expected is not ... and old != expected:
            return False, old
        if value is None:
            blob.pop(key, None)
        else:
            blob[key] = value
        write_deploy_plugin_blob(plugin_name, blob)
        _audit_storage_change(plugin_name, key, old, value)
        return True, old


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
        key_name = key.strip()
        _write_key_locked(self.plugin_name, key_name, value)

    def set_if_current(self, key: str, value: Any, expected: Any) -> bool:
        from pallas.core.storage.store import resolve_decl

        resolve_decl(self.plugin_name, key)
        key_name = key.strip()
        written, _ = _write_key_locked(self.plugin_name, key_name, value, expected)
        return written

    def delete(self, key: str) -> None:
        self.set(key, None)
