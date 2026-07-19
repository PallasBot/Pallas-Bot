from __future__ import annotations

import types

from packages.help import plugin_availability


def test_is_plugin_help_available_caches_result(monkeypatch):
    plugin_availability.invalidate_plugin_help_availability_cache()
    calls = {"n": 0}

    class FakeCfg:
        llm_chat_enabled = True

    def fake_getter():
        calls["n"] += 1
        return FakeCfg()

    fake_mod = types.SimpleNamespace(getter=fake_getter)
    monkeypatch.setattr(plugin_availability, "_CONFIG_GATED", {"ollama": ("fake.mod", "getter", "llm_chat_enabled")})
    monkeypatch.setattr(plugin_availability.importlib, "import_module", lambda _path: fake_mod)

    assert plugin_availability.is_plugin_help_available("ollama") is True
    assert plugin_availability.is_plugin_help_available("ollama") is True
    assert calls["n"] == 1

    plugin_availability.invalidate_plugin_help_availability_cache()
    assert plugin_availability.is_plugin_help_available("ollama") is True
    assert calls["n"] == 2


def test_llm_chat_help_hidden_when_ai_unreachable(monkeypatch):
    plugin_availability.invalidate_plugin_help_availability_cache()

    class FakeCfg:
        llm_chat_enabled = True

    fake_mod = types.SimpleNamespace(get_llm_config=lambda: FakeCfg())
    monkeypatch.setattr(
        plugin_availability,
        "_CONFIG_GATED",
        {"llm_chat": ("fake.mod", "get_llm_config", "llm_chat_enabled")},
    )
    monkeypatch.setattr(plugin_availability.importlib, "import_module", lambda _path: fake_mod)
    monkeypatch.setattr("pallas.product.llm.startup_probe.llm_ai_service_reachable", lambda: False)

    assert plugin_availability.is_plugin_help_available("llm_chat") is False
