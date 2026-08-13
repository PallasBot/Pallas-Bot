from __future__ import annotations

import pytest

from pallas.core.storage.schema import clear_plugin_storage_registry_cache


@pytest.fixture(autouse=True)
def register_help_plugin_storage(monkeypatch, tmp_path):
    """注册 help 插件 storage 声明，并把 deploy 存储重定向到临时目录。"""
    import packages.help

    class FakePlugin:
        name = "help"
        metadata = packages.help.__plugin_meta__

    monkeypatch.setattr("nonebot.get_loaded_plugins", lambda: [FakePlugin()])
    monkeypatch.setattr("pallas.core.storage.deploy_store.plugin_data_dir", lambda _name: tmp_path)
    clear_plugin_storage_registry_cache()
    yield
    clear_plugin_storage_registry_cache()
