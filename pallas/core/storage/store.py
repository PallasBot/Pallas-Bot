"""插件声明式存储读写。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pallas.core.foundation.config import BotConfig, GroupConfig, UserConfig
from pallas.core.storage.schema import storage_decl_for

if TYPE_CHECKING:
    from pallas.core.storage.metadata import PluginStorageDecl

StorageScope = Literal["group", "user", "bot", "deploy"]

PLUGIN_STORAGE_FIELD = "plugin_storage"

_ephemeral_values: dict[tuple[str, str, int, str], Any] = {}


class PluginStorageError(ValueError):
    pass


class PluginStorageKeyError(PluginStorageError):
    pass


def ephemeral_cache_key(scope: StorageScope, plugin_name: str, scope_id: int, key: str) -> tuple[str, str, int, str]:
    return (scope, plugin_name.strip(), int(scope_id), key.strip())


def clear_ephemeral_plugin_storage() -> None:
    _ephemeral_values.clear()


async def read_persisted_blob(scope: StorageScope, scope_id: int) -> dict[str, Any]:
    if scope == "deploy":
        msg = "deploy scope uses DeployPluginStorage, not read_persisted_blob"
        raise PluginStorageError(msg)
    if scope == "group":
        raw = await GroupConfig(scope_id)._find(PLUGIN_STORAGE_FIELD)
    elif scope == "user":
        raw = await UserConfig(scope_id)._find(PLUGIN_STORAGE_FIELD)
    elif scope == "bot":
        raw = await BotConfig(scope_id)._find(PLUGIN_STORAGE_FIELD)
    else:
        msg = f"unknown scope: {scope}"
        raise PluginStorageError(msg)
    return raw if isinstance(raw, dict) else {}


async def write_persisted_blob(scope: StorageScope, scope_id: int, blob: dict[str, Any]) -> None:
    if scope == "deploy":
        msg = "deploy scope uses DeployPluginStorage, not write_persisted_blob"
        raise PluginStorageError(msg)
    if scope == "group":
        await GroupConfig(scope_id)._update(PLUGIN_STORAGE_FIELD, blob)
    elif scope == "user":
        await UserConfig(scope_id)._update(PLUGIN_STORAGE_FIELD, blob)
    elif scope == "bot":
        await BotConfig(scope_id)._update(PLUGIN_STORAGE_FIELD, blob)
    else:
        msg = f"unknown scope: {scope}"
        raise PluginStorageError(msg)


def resolve_decl(plugin_name: str, key: str) -> PluginStorageDecl:
    decl = storage_decl_for(plugin_name, key)
    if decl is None:
        msg = f"undeclared plugin_storage key: {plugin_name}.{key}"
        raise PluginStorageKeyError(msg)
    return decl


async def get_plugin_storage(
    plugin_name: str,
    key: str,
    *,
    scope_id: int,
    scope: StorageScope | None = None,
) -> Any:
    decl = resolve_decl(plugin_name, key)
    active_scope = scope or decl.scope
    if active_scope != decl.scope:
        msg = f"scope mismatch for {plugin_name}.{key}: expected {decl.scope}, got {active_scope}"
        raise PluginStorageError(msg)
    if decl.ephemeral:
        return _ephemeral_values.get(ephemeral_cache_key(active_scope, plugin_name, scope_id, key))
    if active_scope == "deploy":
        from pallas.core.storage.deploy_store import read_deploy_plugin_blob

        return read_deploy_plugin_blob(plugin_name).get(key)
    blob = await read_persisted_blob(active_scope, scope_id)
    plugin_blob = blob.get(plugin_name)
    if not isinstance(plugin_blob, dict):
        return None
    return plugin_blob.get(key)


async def set_plugin_storage(
    plugin_name: str,
    key: str,
    value: Any,
    *,
    scope_id: int,
    scope: StorageScope | None = None,
) -> None:
    decl = resolve_decl(plugin_name, key)
    active_scope = scope or decl.scope
    if active_scope != decl.scope:
        msg = f"scope mismatch for {plugin_name}.{key}: expected {decl.scope}, got {active_scope}"
        raise PluginStorageError(msg)
    if decl.ephemeral:
        cache_key = ephemeral_cache_key(active_scope, plugin_name, scope_id, key)
        if value is None:
            _ephemeral_values.pop(cache_key, None)
        else:
            _ephemeral_values[cache_key] = value
        return
    if active_scope == "deploy":
        from pallas.core.storage.deploy_store import DeployPluginStorage

        store = DeployPluginStorage(plugin_name)
        if value is None:
            store.delete(key)
        else:
            store.set(key, value)
        return
    blob = await read_persisted_blob(active_scope, scope_id)
    plugin_blob = blob.get(plugin_name)
    if not isinstance(plugin_blob, dict):
        plugin_blob = {}
    if value is None:
        plugin_blob.pop(key, None)
        if plugin_blob:
            blob[plugin_name] = plugin_blob
        else:
            blob.pop(plugin_name, None)
    else:
        plugin_blob[key] = value
        blob[plugin_name] = plugin_blob
    await write_persisted_blob(active_scope, scope_id, blob)


async def delete_plugin_storage(
    plugin_name: str,
    key: str,
    *,
    scope_id: int,
    scope: StorageScope | None = None,
) -> None:
    await set_plugin_storage(plugin_name, key, None, scope_id=scope_id, scope=scope)


class GroupPluginStorage:
    def __init__(self, plugin_name: str, group_id: int) -> None:
        self.plugin_name = plugin_name.strip()
        self.group_id = int(group_id)

    async def get(self, key: str) -> Any:
        return await get_plugin_storage(self.plugin_name, key, scope_id=self.group_id, scope="group")

    async def set(self, key: str, value: Any) -> None:
        await set_plugin_storage(self.plugin_name, key, value, scope_id=self.group_id, scope="group")

    async def delete(self, key: str) -> None:
        await delete_plugin_storage(self.plugin_name, key, scope_id=self.group_id, scope="group")
