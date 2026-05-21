from src.common.webui.plugin_catalog import (
    build_plugin_catalog_rows,
    discover_plugin_packages,
    package_load_role,
)


def test_discover_includes_pallas_image():
    pkgs = discover_plugin_packages()
    assert "pallas_image" in pkgs
    assert "pallas_webui" in pkgs


def test_package_load_role_sharded(monkeypatch):
    monkeypatch.setenv("PALLAS_SHARD_ENABLED", "true")
    monkeypatch.setenv("PALLAS_BOT_ROLE", "hub")
    from src.common.shard.registry.config import get_shard_registry_settings

    get_shard_registry_settings.cache_clear()
    assert package_load_role("pallas_image") == "worker"
    assert package_load_role("pallas_webui") == "hub"
    assert package_load_role("callback") == "hub"


def test_catalog_lists_worker_plugin(monkeypatch):
    monkeypatch.setenv("PALLAS_SHARD_ENABLED", "true")
    monkeypatch.setenv("PALLAS_BOT_ROLE", "hub")
    from src.common.shard.registry.config import get_shard_registry_settings

    get_shard_registry_settings.cache_clear()
    rows = build_plugin_catalog_rows()
    by_name = {r["name"]: r for r in rows}
    assert "pallas_image" in by_name
    assert by_name["pallas_image"]["load_role"] == "worker"
    assert by_name["pallas_image"]["metadata"] is not None
