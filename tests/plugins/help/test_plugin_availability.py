from __future__ import annotations

import types

from src.plugins.help import plugin_availability


def test_is_plugin_help_available_caches_result(monkeypatch):
    plugin_availability.invalidate_plugin_help_availability_cache()
    calls = {"n": 0}

    class FakeCfg:
        ollama_enable = True
        llm_chat_enable = True

    def fake_getter():
        calls["n"] += 1
        return FakeCfg()

    fake_mod = types.SimpleNamespace(getter=fake_getter)
    monkeypatch.setattr(plugin_availability, "_CONFIG_GATED", {"ollama": ("fake.mod", "getter", "llm_chat_enable")})
    monkeypatch.setattr(plugin_availability.importlib, "import_module", lambda _path: fake_mod)

    assert plugin_availability.is_plugin_help_available("ollama") is True
    assert plugin_availability.is_plugin_help_available("ollama") is True
    assert calls["n"] == 1

    plugin_availability.invalidate_plugin_help_availability_cache()
    assert plugin_availability.is_plugin_help_available("ollama") is True
    assert calls["n"] == 2
