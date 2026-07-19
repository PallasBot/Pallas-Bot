from __future__ import annotations

from pathlib import Path

from pallas.console.webui.plugin_catalog import resolve_catalog_visuals
from pallas.console.webui.plugin_package_assets import (
    plugin_package_asset_public_url,
    resolve_plugin_package_asset_file,
    resolve_plugin_package_visual_urls,
)


def test_resolve_plugin_package_visual_urls(tmp_path: Path) -> None:
    root = tmp_path / "demo"
    assets = root / "assets"
    assets.mkdir(parents=True)
    (assets / "cover.png").write_bytes(b"png")
    visuals = resolve_plugin_package_visual_urls(plugin_id="demo", plugin_root=root)
    assert visuals["cover"] == "/pallas/plugin-assets/demo/assets/cover.png"
    assert visuals["icon"] == "/pallas/plugin-assets/demo/assets/cover.png"


def test_resolve_plugin_package_asset_file_rejects_traversal(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "arcana"
    assets = root / "assets"
    assets.mkdir(parents=True)
    (root / "__init__.py").write_text("", encoding="utf-8")
    (assets / "cover.png").write_bytes(b"png")
    monkeypatch.setattr(
        "pallas.console.webui.plugin_package_assets.plugin_roots_for_id",
        lambda _pid: [root.resolve()],
    )
    ok = resolve_plugin_package_asset_file("arcana", "assets/cover.png")
    assert ok is not None
    assert resolve_plugin_package_asset_file("arcana", "../secret.txt") is None
    assert resolve_plugin_package_asset_file("bad-id!", "assets/cover.png") is None


def test_resolve_catalog_visuals_prefers_local_over_store_cache(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "demo"
    assets = root / "assets"
    assets.mkdir(parents=True)
    (assets / "cover.png").write_bytes(b"png")
    monkeypatch.setattr(
        "pallas.console.webui.plugin_package_assets.plugin_roots_for_id",
        lambda _pid: [root.resolve()],
    )
    monkeypatch.setattr(
        "pallas.console.webui.plugin_store_assets.resolve_store_cached_visual_urls_for_plugin",
        lambda _pid: {
            "cover": "/pallas/store-assets/cover/community-demo.webp",
            "icon": "/pallas/store-assets/icon/community-demo.png",
            "avatar": None,
        },
    )
    monkeypatch.setattr(
        "pallas.console.webui.plugin_catalog._resolve_remote_catalog_visuals",
        lambda _pid: {
            "cover": "https://raw.githubusercontent.com/acme/demo/main/assets/cover.webp",
            "icon": "https://raw.githubusercontent.com/acme/demo/main/assets/icon.png",
            "avatar": "https://avatars.githubusercontent.com/acme?s=64",
        },
    )

    visuals = resolve_catalog_visuals(plugin_id="demo", plugin_source="local", plugin_root=root)

    assert visuals["cover"] == "/pallas/plugin-assets/demo/assets/cover.png"
    assert visuals["icon"] == visuals["cover"]
    assert visuals["avatar"] == "https://avatars.githubusercontent.com/acme?s=64"


def test_resolve_catalog_visuals_prefers_store_cache_over_remote(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.console.webui.plugin_package_assets.resolve_plugin_package_visual_urls",
        lambda **_: {"cover": None, "icon": None, "avatar": None},
    )
    monkeypatch.setattr(
        "pallas.console.webui.plugin_store_assets.resolve_store_cached_visual_urls_for_plugin",
        lambda _pid: {
            "cover": "/pallas/store-assets/cover/official-draw.webp",
            "icon": "/pallas/store-assets/icon/draw.png",
            "avatar": None,
        },
    )
    monkeypatch.setattr(
        "pallas.console.webui.plugin_catalog._resolve_remote_catalog_visuals",
        lambda _pid: {
            "cover": "https://raw.githubusercontent.com/acme/draw/cover.webp",
            "icon": "https://raw.githubusercontent.com/acme/draw/icon.png",
            "avatar": None,
        },
    )

    visuals = resolve_catalog_visuals(plugin_id="draw", plugin_source="extra")

    assert visuals["cover"] == "/pallas/store-assets/cover/official-draw.webp"
    assert visuals["icon"] == "/pallas/store-assets/cover/official-draw.webp"


def test_plugin_package_assets_revision_changes_when_asset_updated(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "demo"
    assets = root / "assets"
    assets.mkdir(parents=True)
    cover = assets / "cover.png"
    cover.write_bytes(b"v1")
    monkeypatch.setattr(
        "pallas.console.webui.plugin_package_assets._iter_plugin_asset_roots",
        lambda: [("demo", root.resolve())],
    )

    from pallas.console.webui.plugin_package_assets import (
        invalidate_plugin_package_assets_revision,
        plugin_package_assets_revision,
    )

    before = plugin_package_assets_revision(force=True)
    cover.write_bytes(b"version-two-longer")
    invalidate_plugin_package_assets_revision()
    after = plugin_package_assets_revision(force=True)
    assert before != after


def test_plugin_package_assets_revision_uses_ttl_cache(monkeypatch) -> None:
    calls = {"count": 0}

    def fake_scan() -> str:
        calls["count"] += 1
        return "pkgvis=abc"

    monkeypatch.setattr(
        "pallas.console.webui.plugin_package_assets._scan_plugin_package_assets_revision",
        fake_scan,
    )
    from pallas.console.webui.plugin_package_assets import (
        invalidate_plugin_package_assets_revision,
        plugin_package_assets_revision,
    )

    invalidate_plugin_package_assets_revision()
    assert plugin_package_assets_revision() == "pkgvis=abc"
    assert plugin_package_assets_revision() == "pkgvis=abc"
    assert calls["count"] == 1


def test_help_image_cache_suffix_includes_package_assets_revision(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.console.webui.plugin_package_assets.plugin_package_assets_revision",
        lambda: "pkgvis=deadbeef",
    )
    from packages.help.renderer import _compute_help_image_cache_suffix

    suffix = _compute_help_image_cache_suffix()
    assert "pkgvis=deadbeef" in suffix


def test_resolve_catalog_visuals_prefers_package_cover_over_brand_avatar() -> None:
    roulette_root = Path(__file__).resolve().parents[2] / "packages" / "roulette"
    if not (roulette_root / "assets" / "cover.png").is_file():
        return
    visuals = resolve_catalog_visuals(plugin_id="roulette", plugin_source="core", plugin_root=roulette_root)
    assert visuals["cover"] == plugin_package_asset_public_url("roulette", "assets/cover.png")
    assert visuals["icon"] == visuals["cover"]


def test_resolve_plugin_package_visual_urls_without_explicit_root(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "arcana"
    assets = root / "assets"
    assets.mkdir(parents=True)
    (root / "__init__.py").write_text("", encoding="utf-8")
    (assets / "cover.png").write_bytes(b"png")
    monkeypatch.setattr(
        "pallas.console.webui.plugin_package_assets.plugin_roots_for_id",
        lambda _pid: [root.resolve()],
    )
    visuals = resolve_plugin_package_visual_urls(plugin_id="arcana", plugin_root=None)
    assert visuals["cover"] == plugin_package_asset_public_url("arcana", "assets/cover.png")
