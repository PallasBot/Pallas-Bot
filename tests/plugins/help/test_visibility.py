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


def test_console_stats_excluded_matches_help_hidden_infra():
    excluded = _visibility.resolve_console_stats_excluded_plugin_names()
    assert "pb_webui" in excluded
    assert "ingress_gate" in excluded
    assert "ingress_gate" in excluded


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
    llm_chat = SimpleNamespace(
        name="llm_chat",
        metadata=SimpleNamespace(name="随时闲聊", extra={"help_audience": "superuser"}),
    )
    draw = SimpleNamespace(name="draw", metadata=SimpleNamespace(name="牛牛画画", extra={}))

    monkeypatch.setattr(pm, "get_loaded_plugins", lambda: [pb_core, llm_chat, draw])
    monkeypatch.setattr(pm, "is_plugin_help_available", lambda _name: True)

    user_menu = pm.get_help_menu_plugins(show_ignored=False, ignored_plugins=[])
    superuser_menu = pm.get_help_menu_plugins(show_ignored=True)

    assert {p.name for p in user_menu} == {"draw"}
    assert {p.name for p in superuser_menu} == {"pb_core", "llm_chat", "draw"}
