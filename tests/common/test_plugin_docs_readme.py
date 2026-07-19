from __future__ import annotations

from pathlib import Path

from pallas.console.webui.plugin_docs_readme import normalize_bundled_plugin_readme_markdown


def test_normalize_bundled_readme_swaps_brand_avatar_for_package_cover() -> None:
    drink_root = Path(__file__).resolve().parents[2] / "packages" / "drink"
    if not (drink_root / "assets" / "cover.png").is_file():
        return
    md = '<p align="center"><img src="../assets/brand-avatar.png" width="220" alt="牛牛喝酒"></p>'
    out = normalize_bundled_plugin_readme_markdown("drink", md)
    assert "/pallas/plugin-assets/drink/assets/cover.png" in out
    assert "brand-avatar" not in out


def test_normalize_bundled_readme_keeps_brand_avatar_without_package_cover() -> None:
    md = '<img src="../assets/brand-avatar.png" width="220" alt="示例">'
    out = normalize_bundled_plugin_readme_markdown("pb_core", md)
    assert "/pallas/assets/brand-avatar.png" in out
    assert "/pallas/plugin-assets/pb_core/assets/cover" not in out


def test_normalize_bundled_readme_rewrites_plugin_relative_assets() -> None:
    md = "![cover](./assets/cover.png)"
    out = normalize_bundled_plugin_readme_markdown("drink", md)
    assert out == "![cover](/pallas/plugin-assets/drink/assets/cover.png)"


def test_normalize_bundled_readme_uses_official_extension_cover_for_maa() -> None:
    md = '<p align="center"><img src="../assets/brand-avatar.png" width="220" alt="MAA"></p>'
    out = normalize_bundled_plugin_readme_markdown("maa", md)
    assert "raw.githubusercontent.com/TogetsuDo/pallas-plugin-maa/main/assets/brand-avatar.png" in out
    assert "/pallas/assets/brand-avatar.png" not in out


def test_normalize_bundled_readme_uses_official_extension_cover_for_chat() -> None:
    md = '<p align="center"><img src="../assets/brand-avatar.png" width="220" alt="chat"></p>'
    out = normalize_bundled_plugin_readme_markdown("chat", md)
    assert "raw.githubusercontent.com/TogetsuDo/pallas-plugin-ai-media/main/assets/brand-avatar.png" in out
    assert "/pallas/assets/brand-avatar.png" not in out


def test_normalize_bundled_readme_keeps_brand_avatar_for_non_official_plugin() -> None:
    md = '<img src="../assets/brand-avatar.png" width="220" alt="示例">'
    out = normalize_bundled_plugin_readme_markdown("my_community_demo_plugin", md)
    assert "/pallas/assets/brand-avatar.png" in out
