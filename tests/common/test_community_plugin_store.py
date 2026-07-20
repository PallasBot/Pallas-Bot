from __future__ import annotations

import pytest

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


@pytest.mark.asyncio
async def test_install_community_plugin_uses_rewritten_clone_url(monkeypatch, tmp_path) -> None:
    from pallas.console.webui import community_plugin_install as cpi
    from pallas.core.shared.utils import git_mirror as gm

    ghproxy_mirror = next(m for m in gm.BUILTIN_MIRRORS if m.id == "ghproxy-vip")

    def fake_iter_mirrors():
        yield ghproxy_mirror

    monkeypatch.setattr(cpi, "iter_mirrors_for_failover", fake_iter_mirrors)
    monkeypatch.setattr(cpi, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cpi, "extra_plugin_dirs_ready", lambda: True)
    monkeypatch.setattr(cpi, "bot_lifecycle_available", lambda: True)
    monkeypatch.setattr(cpi.shutil, "which", lambda _cmd: "/usr/bin/git")

    clone_urls: list[str] = []

    async def fake_run_git_command(_timeout_s: float, *args: str, cwd: str | None = None):
        if args and args[0] == "clone":
            clone_urls.append(args[5])
            dest = tmp_path / cpi.COMMUNITY_PLUGINS_DIR / "demo"
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "__init__.py").write_text("# demo\n", encoding="utf-8")
            return 0, "cloned", ""
        return 1, "", "unexpected git args"

    monkeypatch.setattr(cpi, "run_git_command", fake_run_git_command)

    result = await cpi.install_community_plugin(
        "demo",
        repository_url="https://github.com/acme/demo",
        ref="main",
    )

    assert result["installed"] is True
    assert len(clone_urls) == 1
    assert clone_urls[0] == "https://ghproxy.vip/https://github.com/acme/demo"


@pytest.mark.asyncio
async def test_update_community_plugin_uses_git_instead_of_for_proxy(monkeypatch, tmp_path) -> None:
    from pallas.console.webui import community_plugin_install as cpi
    from pallas.core.shared.utils import git_mirror as gm

    ghproxy_mirror = next(m for m in gm.BUILTIN_MIRRORS if m.id == "ghproxy-vip")

    def fake_iter_mirrors():
        yield ghproxy_mirror

    monkeypatch.setattr(cpi, "iter_mirrors_for_failover", fake_iter_mirrors)
    monkeypatch.setattr(cpi, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cpi, "extra_plugin_dirs_ready", lambda: True)
    monkeypatch.setattr(cpi, "bot_lifecycle_available", lambda: True)

    dest = tmp_path / cpi.COMMUNITY_PLUGINS_DIR / "demo"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "__init__.py").write_text("# demo\n", encoding="utf-8")

    git_calls: list[tuple[str, ...]] = []

    async def fake_run_git_command(_timeout_s: float, *args: str, cwd: str | None = None):
        git_calls.append(args)
        if args[-3:] == ("reset", "--hard", "origin/main"):
            return 0, "reset ok", ""
        if args[-3:] == ("fetch", "origin", "main"):
            return 0, "fetched", ""
        return 1, "", "fail"

    monkeypatch.setattr(cpi, "run_git_command", fake_run_git_command)

    result = await cpi.update_community_plugin("demo", ref="main")

    assert result["installed"] is True
    assert any(
        args[:2] == ("-c", "url.https://ghproxy.vip/https://github.com/.insteadOf=https://github.com/")
        for args in git_calls
    )
