from __future__ import annotations

from pallas.console.webui.community_plugin_registry import build_community_plugin_store


async def test_build_community_plugin_store_skips_local_only_plugins(monkeypatch) -> None:
    async def fake_index():
        return {
            "plugins": [
                {
                    "plugin_id": "demo",
                    "name": "Demo",
                    "repository_url": "https://github.com/acme/demo",
                }
            ],
            "meta": {},
        }

    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.load_community_plugin_index_safe",
        fake_index,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.local_plugin_installed",
        lambda plugin_id: plugin_id == "demo",
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.loaded_extra_plugin_ids",
        lambda plugin_ids: [],
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.webui_community_install_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.bot_lifecycle_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.extra_plugin_dirs_ready",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.resolve_community_plugin_icon",
        lambda entry: None,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.list_local_community_plugin_ids",
        lambda: ["demo", "local_only_plugin"],
    )

    store = await build_community_plugin_store()

    assert [row["plugin_id"] for row in store["plugins"]] == ["demo"]


async def test_build_community_plugin_store_uses_author_avatar(monkeypatch) -> None:
    async def fake_index():
        return {
            "plugins": [
                {
                    "plugin_id": "demo",
                    "name": "Demo",
                    "author": "acme",
                    "repository_url": "https://github.com/acme/demo",
                    "ref": "main",
                }
            ],
            "meta": {},
        }

    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.load_community_plugin_index_safe",
        fake_index,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.local_plugin_installed",
        lambda plugin_id: False,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.loaded_extra_plugin_ids",
        lambda plugin_ids: [],
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.webui_community_install_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.bot_lifecycle_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.extra_plugin_dirs_ready",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.resolve_community_plugin_icon",
        lambda entry: "https://raw.githubusercontent.com/acme/demo/main/assets/icon.png",
    )
    store = await build_community_plugin_store()
    row = store["plugins"][0]

    assert row["avatar"] == "https://avatars.githubusercontent.com/acme?s=64"


async def test_build_community_plugin_store_prefers_author_avatar_over_plugin_avatar_field(monkeypatch) -> None:
    async def fake_index():
        return {
            "plugins": [
                {
                    "plugin_id": "demo",
                    "name": "Demo",
                    "author": "acme",
                    "repository_url": "https://github.com/acme/demo",
                    "ref": "main",
                    "avatar": "https://raw.githubusercontent.com/acme/demo/main/assets/avatar.png",
                }
            ],
            "meta": {},
        }

    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.load_community_plugin_index_safe",
        fake_index,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.local_plugin_installed",
        lambda plugin_id: False,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.loaded_extra_plugin_ids",
        lambda plugin_ids: [],
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.webui_community_install_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.bot_lifecycle_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.extra_plugin_dirs_ready",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.resolve_community_plugin_icon",
        lambda entry: "https://raw.githubusercontent.com/acme/demo/main/assets/icon.png",
    )

    store = await build_community_plugin_store()
    row = store["plugins"][0]

    assert row["avatar"] == "https://avatars.githubusercontent.com/acme?s=64"


def test_resolve_community_plugin_avatar_uses_author_avatar(monkeypatch) -> None:
    from pallas.console.webui.community_plugin_registry import resolve_community_plugin_avatar

    assert (
        resolve_community_plugin_avatar({
            "author": "acme",
            "repository_url": "https://github.com/acme/demo",
            "ref": "main",
        })
        == "https://avatars.githubusercontent.com/acme?s=64"
    )


async def test_build_community_plugin_store_falls_back_to_author_avatar_when_no_explicit_avatar(monkeypatch) -> None:
    async def fake_index():
        return {
            "plugins": [
                {
                    "plugin_id": "demo",
                    "name": "Demo",
                    "author": "acme",
                    "repository_url": "https://github.com/acme/demo",
                    "ref": "main",
                }
            ],
            "meta": {},
        }

    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.load_community_plugin_index_safe",
        fake_index,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.local_plugin_installed",
        lambda plugin_id: False,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.loaded_extra_plugin_ids",
        lambda plugin_ids: [],
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.webui_community_install_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.bot_lifecycle_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.extra_plugin_dirs_ready",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.resolve_community_plugin_icon",
        lambda entry: "https://raw.githubusercontent.com/acme/demo/main/assets/icon.png",
    )
    store = await build_community_plugin_store()
    row = store["plugins"][0]

    assert row["avatar"] == "https://avatars.githubusercontent.com/acme?s=64"


async def test_build_community_plugin_store_prefers_repo_cover_from_backend(monkeypatch) -> None:
    async def fake_index():
        return {
            "plugins": [
                {
                    "plugin_id": "demo",
                    "name": "Demo",
                    "repository_url": "https://github.com/acme/demo",
                    "ref": "main",
                }
            ],
            "meta": {},
        }

    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.load_community_plugin_index_safe",
        fake_index,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.local_plugin_installed",
        lambda plugin_id: False,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.loaded_extra_plugin_ids",
        lambda plugin_ids: [],
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.webui_community_install_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.bot_lifecycle_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.extra_plugin_dirs_ready",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.resolve_community_plugin_icon",
        lambda entry: "https://raw.githubusercontent.com/acme/demo/main/assets/icon.png",
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.resolve_community_plugin_avatar",
        lambda entry: "https://raw.githubusercontent.com/acme/demo/main/assets/avatar.png",
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.resolve_community_plugin_cover",
        lambda entry: "https://raw.githubusercontent.com/acme/demo/main/assets/cover.webp",
    )

    store = await build_community_plugin_store()
    row = store["plugins"][0]

    assert row["cover"] == "https://raw.githubusercontent.com/acme/demo/main/assets/cover.webp"


async def test_build_community_plugin_store_prefers_cached_asset_urls(monkeypatch) -> None:
    async def fake_index():
        return {
            "plugins": [
                {
                    "plugin_id": "demo",
                    "name": "Demo",
                    "repository_url": "https://github.com/acme/demo",
                    "ref": "main",
                }
            ],
            "meta": {},
        }

    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.load_community_plugin_index_safe",
        fake_index,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.local_plugin_installed",
        lambda plugin_id: False,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.loaded_extra_plugin_ids",
        lambda plugin_ids: [],
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.webui_community_install_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.bot_lifecycle_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.extra_plugin_dirs_ready",
        lambda: True,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.resolve_community_plugin_icon",
        lambda entry: "https://raw.githubusercontent.com/acme/demo/main/assets/icon.png",
    )
    monkeypatch.setattr(
        "pallas.console.webui.plugin_store_assets.apply_asset_snapshot_to_rows",
        lambda kind, rows: (
            [{**rows[0], "icon": "/pallas/store-assets/icon/community-demo.png"}] if kind == "community" else rows
        ),
    )

    store = await build_community_plugin_store()
    row = store["plugins"][0]

    assert row["icon"] == "/pallas/store-assets/icon/community-demo.png"
