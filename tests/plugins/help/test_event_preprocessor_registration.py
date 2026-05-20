"""help 须 import event_preprocessor，否则群内禁用不会拦截其它 matcher。"""

from pathlib import Path

from nonebot.message import _event_preprocessors, _run_preprocessors

from src.plugins.help.event_preprocessor import block_disabled_plugins, check_plugin_enabled


def test_help_init_imports_event_preprocessor_module() -> None:
    init_text = Path("src/plugins/help/__init__.py").read_text(encoding="utf-8")
    assert "event_preprocessor" in init_text


def _registered_preprocessor_names(preprocessors: set) -> set[str]:
    names: set[str] = set()
    for item in preprocessors:
        call = getattr(item, "call", item)
        names.add(getattr(call, "__name__", ""))
    return names


def test_disable_preprocessors_registered() -> None:
    event_names = _registered_preprocessor_names(_event_preprocessors)
    run_names = _registered_preprocessor_names(_run_preprocessors)
    assert block_disabled_plugins.__name__ in event_names
    assert check_plugin_enabled.__name__ in run_names
