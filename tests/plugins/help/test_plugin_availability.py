from __future__ import annotations

import types

from packages.help import plugin_availability
from pallas.product.llm import config as llm_config
from pallas.product.llm import startup_probe as llm_probe


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
    monkeypatch.setattr(llm_config, "is_llm_bot_kernel_runtime", lambda _cfg=None: False)
    monkeypatch.setattr(llm_probe, "llm_ai_service_reachable", lambda: True)

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
        llm_runtime = "ai_service"
        llm_base_url = ""
        llm_model = ""

    fake_mod = types.SimpleNamespace(get_llm_config=lambda: FakeCfg())
    monkeypatch.setattr(
        plugin_availability,
        "_CONFIG_GATED",
        {"llm_chat": ("fake.mod", "get_llm_config", "llm_chat_enabled")},
    )
    monkeypatch.setattr(plugin_availability.importlib, "import_module", lambda _path: fake_mod)
    monkeypatch.setattr(llm_config, "get_llm_config", lambda: FakeCfg())
    monkeypatch.setattr(llm_config, "is_llm_bot_kernel_runtime", lambda _cfg=None: False)
    monkeypatch.setattr(llm_probe, "llm_ai_service_reachable", lambda: False)

    assert plugin_availability.is_plugin_help_available("llm_chat") is False


def test_llm_chat_help_hidden_when_kernel_provider_missing(monkeypatch):
    plugin_availability.invalidate_plugin_help_availability_cache()

    class FakeCfg:
        llm_chat_enabled = True
        llm_runtime = "bot_kernel"
        llm_base_url = ""
        llm_model = ""

    fake_mod = types.SimpleNamespace(get_llm_config=lambda: FakeCfg())
    monkeypatch.setattr(
        plugin_availability,
        "_CONFIG_GATED",
        {"llm_chat": ("fake.mod", "get_llm_config", "llm_chat_enabled")},
    )
    monkeypatch.setattr(plugin_availability.importlib, "import_module", lambda _path: fake_mod)
    monkeypatch.setattr(llm_config, "get_llm_config", lambda: FakeCfg())
    monkeypatch.setattr(llm_config, "is_llm_bot_kernel_runtime", lambda _cfg=None: True)
    monkeypatch.setattr(llm_config, "llm_provider_configured", lambda _cfg=None: False)
    monkeypatch.setattr(llm_probe, "llm_provider_ready", lambda: None)

    assert plugin_availability.is_plugin_help_available("llm_chat") is False
