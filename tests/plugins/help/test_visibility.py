import importlib.util
from pathlib import Path

_visibility_path = Path(__file__).resolve().parents[3] / "src" / "plugins" / "help" / "visibility.py"
_spec = importlib.util.spec_from_file_location("_help_visibility_under_test", _visibility_path)
assert _spec is not None
assert _spec.loader is not None
_visibility = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_visibility)


def test_builtin_help_hidden_includes_infra_plugins():
    hidden = _visibility.BUILTIN_HELP_HIDDEN_PLUGINS
    assert "_ingress_gate" in hidden
    assert "pallas_console_metrics" in hidden
    assert "_ingress_gate" in _visibility.resolve_help_hidden_plugins()
    assert "pallas_console_metrics" in _visibility.resolve_help_hidden_plugins()


def test_console_stats_excluded_matches_help_hidden_infra():
    excluded = _visibility.resolve_console_stats_excluded_plugin_names()
    assert "pallas_webui" in excluded
    assert "_ingress_gate" in excluded
    assert "pallas_console_metrics" in excluded
    assert "ingress_gate" in excluded
