import importlib.util
from pathlib import Path
from types import SimpleNamespace

_visibility_path = Path(__file__).resolve().parents[3] / "packages" / "help" / "visibility.py"
_spec = importlib.util.spec_from_file_location("_help_visibility_under_test", _visibility_path)
assert _spec is not None
assert _spec.loader is not None
_visibility = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_visibility)


def test_builtin_help_hidden_includes_infra_plugins():
    hidden = _visibility.BUILTIN_HELP_HIDDEN_PLUGINS
    assert "ingress_gate" in hidden
    assert "pb_stats" in hidden
    assert "relogin_forward" in hidden
    assert "pb_stats" in _visibility.resolve_help_hidden_plugins()
    from packages.help.plugin_legacy_names import is_plugin_name_in_set

    assert is_plugin_name_in_set("community_stats", hidden)


def test_plugin_disable_matches_pip_module_alias():
    from packages.help.plugin_legacy_names import is_plugin_name_in_set

    assert is_plugin_name_in_set("pallas_plugin_tts", {"tts"})


def test_console_stats_excluded_matches_help_hidden_infra():
    excluded = _visibility.resolve_console_stats_excluded_plugin_names()
    assert "pb_webui" in excluded
    assert "ingress_gate" in excluded
    assert "ingress_gate" in excluded


def test_get_help_menu_plugins_hidden_matches_pip_module_name(monkeypatch):
    from packages.help import plugin_manager as pm

    tts = SimpleNamespace(name="pallas_plugin_tts", metadata=SimpleNamespace(name="牛牛说", extra={}))
    sing = SimpleNamespace(name="pallas_plugin_sing", metadata=SimpleNamespace(name="牛牛唱歌", extra={}))

    monkeypatch.setattr(pm, "get_loaded_plugins", lambda: [tts, sing])
    monkeypatch.setattr(pm, "is_plugin_help_available", lambda _name: True)
    monkeypatch.setattr(
        "packages.help.visibility.load_help_hidden_plugins",
        lambda: ["tts"],
    )

    menu = pm.get_help_menu_plugins(show_ignored=True)
    names = {p.name for p in menu}
    assert "pallas_plugin_tts" not in names
    assert "pallas_plugin_sing" in names


def test_get_help_menu_plugins_always_excludes_hidden(monkeypatch):
    from packages.help import plugin_manager as pm

    ingress = SimpleNamespace(name="ingress_gate", metadata=SimpleNamespace(name="入站网关", extra={}))
    draw = SimpleNamespace(name="draw", metadata=SimpleNamespace(name="牛牛画画", extra={}))

    monkeypatch.setattr(pm, "get_loaded_plugins", lambda: [ingress, draw])
    monkeypatch.setattr(pm, "is_plugin_help_available", lambda _name: True)

    menu = pm.get_help_menu_plugins(show_ignored=True)
    names = {p.name for p in menu}
    assert "ingress_gate" not in names
    assert "draw" in names


def test_superuser_only_plugins_hidden_from_user_help_but_visible_in_superuser_help(monkeypatch):
    from packages.help import plugin_manager as pm

    pb_core = SimpleNamespace(
        name="pb_core",
        metadata=SimpleNamespace(name="牛牛核心", extra={"help_audience": "superuser"}),
    )
    draw = SimpleNamespace(name="draw", metadata=SimpleNamespace(name="牛牛画画", extra={}))
    llm_chat = SimpleNamespace(
        name="llm_chat",
        metadata=SimpleNamespace(name="智能对话", extra={}),
    )

    monkeypatch.setattr(pm, "get_loaded_plugins", lambda: [pb_core, draw, llm_chat])
    monkeypatch.setattr(pm, "is_plugin_help_available", lambda _name: True)

    user_menu = pm.get_help_menu_plugins(show_ignored=False, ignored_plugins=[])
    superuser_menu = pm.get_help_menu_plugins(show_ignored=True)

    assert {p.name for p in user_menu} == {"draw", "llm_chat"}
    assert {p.name for p in superuser_menu} == {"pb_core", "draw", "llm_chat"}


def test_get_help_menu_plugins_sorted_by_help_tag_then_display_name(monkeypatch):
    from packages.help import plugin_manager as pm

    zebra_fun = SimpleNamespace(
        name="zebra",
        metadata=SimpleNamespace(name="ZebraFun", extra={"help_tag": "fun"}),
    )
    apple_core = SimpleNamespace(
        name="apple",
        metadata=SimpleNamespace(name="AppleCore", extra={"help_tag": "core"}),
    )
    banana_fun = SimpleNamespace(
        name="banana",
        metadata=SimpleNamespace(name="BananaFun", extra={"help_tag": "fun"}),
    )
    other_plug = SimpleNamespace(
        name="misc",
        metadata=SimpleNamespace(name="Misc", extra={"help_tag": "other"}),
    )

    monkeypatch.setattr(pm, "get_loaded_plugins", lambda: [zebra_fun, apple_core, banana_fun, other_plug])
    monkeypatch.setattr(pm, "is_plugin_help_available", lambda _name: True)
    monkeypatch.setattr(pm, "resolve_help_tag_overrides", dict)

    menu = pm.get_help_menu_plugins(show_ignored=True)
    assert [p.name for p in menu] == ["apple", "banana", "zebra", "misc"]
