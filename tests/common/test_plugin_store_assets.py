from __future__ import annotations

from typing import TYPE_CHECKING

from pallas.console.webui import plugin_store_assets as mod

if TYPE_CHECKING:
    from pathlib import Path


def test_apply_asset_snapshot_to_official_rows_prefers_cached_urls(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mod, "plugin_data_dir", lambda _name, create=True: tmp_path)
    mod.save_snapshot({
        "official": {
            "pallas-plugin-draw": {
                "assets": {
                    "icon": {"public_url": "/pallas/store-assets/icon/draw.png"},
                    "cover": {"public_url": "/pallas/store-assets/cover/draw.webp"},
                }
            }
        }
    })
    rows = [
        {
            "package": "pallas-plugin-draw",
            "plugin_ids": ["draw"],
            "icon": "https://raw.githubusercontent.com/acme/draw/icon.png",
            "cover": "https://raw.githubusercontent.com/acme/draw/cover.webp",
            "avatar": None,
        }
    ]

    out = mod.apply_asset_snapshot_to_rows("official", rows)

    assert out[0]["cover"] == "/pallas/store-assets/cover/draw.webp"
    assert out[0]["icon"] == "/pallas/store-assets/cover/draw.webp"


def test_get_cached_readme_markdown_reads_saved_snapshot(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mod, "plugin_data_dir", lambda _name, create=True: tmp_path)
    readme_path = tmp_path / "store-assets" / "readme" / "draw.md"
    readme_path.parent.mkdir(parents=True, exist_ok=True)
    readme_path.write_text("# Draw\n", encoding="utf-8")
    mod.save_snapshot({
        "official": {
            "pallas-plugin-draw": {
                "readme": {
                    "public_url": "/pallas/store-assets/readme/draw.md",
                    "relative_path": "readme/draw.md",
                }
            }
        }
    })

    markdown = mod.get_cached_readme_markdown("official", "pallas-plugin-draw")

    assert markdown == "# Draw\n"


def test_snapshot_has_assets_for_kind_detects_ready_bucket(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mod, "plugin_data_dir", lambda _name, create=True: tmp_path)
    mod.save_snapshot({
        "official": {
            "pallas-plugin-draw": {
                "assets": {
                    "cover": {"public_url": "/pallas/store-assets/cover/draw.webp"},
                }
            }
        },
        "community": {},
    })

    assert mod.snapshot_has_assets_for_kind("official") is True
    assert mod.snapshot_has_assets_for_kind("community") is False


def test_resolve_readme_request_id_accepts_official_plugin_id() -> None:
    assert mod.resolve_readme_request_id("official", "sing") == "pallas-plugin-ai-media"
    assert mod.resolve_readme_request_id("official", "pallas-plugin-draw") == "pallas-plugin-draw"
    assert mod.resolve_readme_request_id("community", "interact") == "interact"


def test_refresh_asset_snapshot_keeps_existing_asset_when_download_fails(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mod, "plugin_data_dir", lambda _name, create=True: tmp_path)
    asset_path = tmp_path / "public" / "store-assets" / "icon" / "draw.png"
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_bytes(b"old-bytes")
    mod.save_snapshot({
        "official": {
            "pallas-plugin-draw": {
                "assets": {
                    "icon": {
                        "source_url": "https://raw.githubusercontent.com/acme/draw/icon.png",
                        "public_url": "/pallas/store-assets/icon/draw.png",
                        "relative_path": "public/store-assets/icon/draw.png",
                    }
                }
            }
        }
    })

    async def fake_collect_targets() -> dict[str, list[dict[str, object]]]:
        return {
            "official": [
                {
                    "id": "pallas-plugin-draw",
                    "repository_url": "https://github.com/acme/draw",
                    "assets": {"icon": "https://raw.githubusercontent.com/acme/draw/icon.png"},
                    "readme_url": "https://raw.githubusercontent.com/acme/draw/main/README.md",
                }
            ]
        }

    async def fake_download_binary(_url: str):
        raise RuntimeError("boom")

    monkeypatch.setattr(mod, "collect_store_asset_targets", fake_collect_targets)
    monkeypatch.setattr(mod, "_download_binary", fake_download_binary)
    monkeypatch.setattr(mod, "_download_text", fake_download_binary)

    snapshot = mod.run_async(mod.refresh_store_asset_snapshot())

    assert asset_path.read_bytes() == b"old-bytes"
    assert (
        snapshot["official"]["pallas-plugin-draw"]["assets"]["icon"]["public_url"]
        == "/pallas/store-assets/icon/draw.png"
    )


def test_collect_store_asset_targets_uses_author_avatar_for_community(monkeypatch) -> None:
    async def fake_index():
        return {
            "plugins": [
                {
                    "plugin_id": "demo",
                    "author": "acme",
                    "repository_url": "https://github.com/acme/demo",
                    "ref": "main",
                    "icon": "https://raw.githubusercontent.com/acme/demo/main/assets/icon.png",
                    "cover": "https://raw.githubusercontent.com/acme/demo/main/assets/cover.webp",
                    "avatar": "https://raw.githubusercontent.com/acme/demo/main/assets/avatar.png",
                }
            ]
        }

    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_index.load_community_plugin_index_safe",
        fake_index,
    )
    monkeypatch.setattr(
        "pallas.console.webui.community_plugin_registry.resolve_community_plugin_avatar",
        lambda entry: "https://avatars.githubusercontent.com/acme?s=64",
    )

    targets = mod.run_async(mod.collect_store_asset_targets())
    community = targets["community"][0]

    assert community["assets"]["avatar"] == "https://avatars.githubusercontent.com/acme?s=64"
