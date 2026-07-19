from pathlib import Path
from types import SimpleNamespace

from packages.help.plugin_visuals import (
    _fallback_label,
    brand_avatar_icon_path,
    load_help_plugin_icon,
    pick_help_icon_url,
    plugin_cover_hue,
    resolve_help_icon_path,
)


def test_pick_help_icon_url_priority() -> None:
    assert pick_help_icon_url({"cover": "c", "icon": "i", "avatar": "a"}) == "c"
    assert pick_help_icon_url({"cover": None, "icon": "i", "avatar": "a"}) == "i"
    assert pick_help_icon_url({"cover": None, "icon": None, "avatar": "a"}) == "a"
    assert pick_help_icon_url({}) is None


def test_fallback_label_chinese() -> None:
    assert _fallback_label("牛牛画画") == "牛"


def test_fallback_label_ascii() -> None:
    assert _fallback_label("draw") == "D"


def test_plugin_cover_hue_range() -> None:
    assert 0 <= plugin_cover_hue("pb_core") < 360


def test_load_help_plugin_icon_falls_back_to_brand_avatar() -> None:
    assert brand_avatar_icon_path() is not None
    plugin = SimpleNamespace(name="unknown_plugin", module=SimpleNamespace(__file__=__file__), metadata=None)
    icon = load_help_plugin_icon(plugin, size=64, label="未知插件")
    assert icon.size == (64, 64)
    assert icon.mode == "RGBA"


def test_local_plugin_asset_precedes_core_brand_avatar() -> None:
    roulette_init = Path(__file__).resolve().parents[3] / "packages" / "roulette" / "__init__.py"
    plugin = SimpleNamespace(name="roulette", module=SimpleNamespace(__file__=str(roulette_init)), metadata=None)
    path = resolve_help_icon_path(plugin)
    assert path is not None
    assert path.name == "cover.png"
    assert path.parent.name == "assets"
