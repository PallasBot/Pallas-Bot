import importlib.util
from pathlib import Path
from types import SimpleNamespace

_visibility_path = Path(__file__).resolve().parents[3] / "src" / "plugins" / "help" / "visibility.py"
_spec = importlib.util.spec_from_file_location("_help_visibility_under_test", _visibility_path)
assert _spec is not None
assert _spec.loader is not None
_visibility = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_visibility)


def test_builtin_help_hidden_includes_infra_plugins():
    hidden = _visibility.BUILTIN_HELP_HIDDEN_PLUGINS
    assert "ingress_gate" in hidden
    assert "community_stats" in hidden
    assert "relogin_forward" in hidden
    assert "community_stats" in _visibility.resolve_help_hidden_plugins()


def test_console_stats_excluded_matches_help_hidden_infra():
    excluded = _visibility.resolve_console_stats_excluded_plugin_names()
    assert "pallas_webui" in excluded
    assert "ingress_gate" in excluded
    assert "ingress_gate" in excluded


def test_get_help_menu_plugins_always_excludes_hidden(monkeypatch):
    from src.plugins.help import plugin_manager as pm

    ingress = SimpleNamespace(name="ingress_gate", metadata=SimpleNamespace(name="入站网关", extra={}))
    draw = SimpleNamespace(name="draw", metadata=SimpleNamespace(name="牛牛画画", extra={}))

    monkeypatch.setattr(pm, "get_loaded_plugins", lambda: [ingress, draw])
    monkeypatch.setattr(pm, "is_plugin_help_available", lambda _name: True)

    menu = pm.get_help_menu_plugins(show_ignored=True)
    names = {p.name for p in menu}
    assert "ingress_gate" not in names
    assert "draw" in names
