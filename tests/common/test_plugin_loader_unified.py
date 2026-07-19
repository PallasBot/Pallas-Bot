from __future__ import annotations

import sys

import nonebot
import pytest

from pallas.core.foundation.paths import PROJECT_ROOT
from pallas.core.platform.bot_runtime.plugin_loader import (
    _discover_plugin_modules,
    _short_name,
    load_plugins_for_role,
)
from pallas.core.platform.bot_runtime.plugin_matrix import CORE_PLUGIN_NAMES
from pallas.core.platform.bot_runtime.roles import UNIFIED_SKIP_PLUGIN_NAMES
from pallas.core.platform.shard.registry.config import get_shard_registry_settings

_PACKAGES = PROJECT_ROOT / "packages"


@pytest.fixture(autouse=True)
def clear_shard_settings_cache():
    get_shard_registry_settings.cache_clear()
    yield
    get_shard_registry_settings.cache_clear()


def test_unified_skip_plugin_names():
    assert UNIFIED_SKIP_PLUGIN_NAMES == frozenset({
        "relogin_forward",
        "maa_hub",
    })


def test_discover_plugin_modules_excludes_underscore_packages():
    names = {_short_name(m) for m in _discover_plugin_modules(load_bundled_extra=True)}
    assert "ingress_gate" not in names
    # 4.0 slim：核心插件在 packages/；分片/扩展插件已外置，仅在目录存在时断言
    for core in ("repeater", "help", "pb_core"):
        assert core in names
    if (_PACKAGES / "relogin_forward").is_dir():
        assert "relogin_forward" in names
    if (_PACKAGES / "maa_hub").is_dir():
        assert "maa_hub" in names


def test_discover_plugin_modules_slim_skips_extra():
    names = {_short_name(m) for m in _discover_plugin_modules(load_bundled_extra=False)}
    assert "repeater" in names
    assert "help" in names
    assert "duel" not in names
    assert "draw" not in names
    assert "maa" not in names
    assert "pb_protocol" not in names


def test_discover_plugin_modules_auto_respects_pip_extra(monkeypatch):
    monkeypatch.setattr(
        "pallas.core.platform.bot_runtime.plugin_matrix.pip_extra_installed_for_plugin",
        lambda _name: False,
    )
    names = {_short_name(m) for m in _discover_plugin_modules(load_bundled_extra="auto")}
    # duel 仅当仍以 packages/duel 捆绑时才会出现
    if (_PACKAGES / "duel").is_dir():
        assert "duel" in names
    else:
        assert "duel" not in names
    assert "draw" not in names


def test_discover_plugin_modules_auto_skips_extra_when_pip_installed(monkeypatch):
    monkeypatch.setattr(
        "pallas.core.platform.bot_runtime.plugin_matrix.pip_extra_installed_for_plugin",
        lambda name: name == "duel",
    )
    names = {_short_name(m) for m in _discover_plugin_modules(load_bundled_extra="auto")}
    assert "duel" not in names


def test_unified_role_loads_core_and_skips_shard_only(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PALLAS_SHARD_ENABLED", raising=False)
    monkeypatch.delenv("PALLAS_BOT_ROLE", raising=False)
    monkeypatch.setenv("PALLAS_LOAD_BUNDLED_EXTRA", "1")
    get_shard_registry_settings.cache_clear()

    nonebot.init()
    load_plugins_for_role()

    loaded = {p.name for p in nonebot.get_loaded_plugins()}
    assert "relogin_forward" not in loaded
    assert "maa_hub" not in loaded
    for name in CORE_PLUGIN_NAMES:
        if (_PACKAGES / name).is_dir():
            assert name in loaded
    assert "ingress_gate" not in loaded


def test_unified_role_slim_skips_bundled_extra(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PALLAS_LOAD_BUNDLED_EXTRA", raising=False)
    names = {_short_name(m) for m in _discover_plugin_modules(load_bundled_extra=False)}
    assert "repeater" in names
    assert "duel" not in names
    assert "draw" not in names


def test_worker_role_skips_maa_hub(monkeypatch: pytest.MonkeyPatch):
    if not (_PACKAGES / "maa").is_dir():
        pytest.skip("maa 未捆绑于 4.0 slim packages/")
    monkeypatch.setenv("PALLAS_SHARD_ENABLED", "true")
    monkeypatch.setenv("PALLAS_BOT_ROLE", "worker")
    monkeypatch.setenv("PALLAS_LOAD_BUNDLED_EXTRA", "1")
    get_shard_registry_settings.cache_clear()

    nonebot.init()
    load_plugins_for_role()

    loaded = {p.name for p in nonebot.get_loaded_plugins()}
    assert "maa_hub" not in loaded
    assert "maa" in loaded


def test_register_kernel_runtime_does_not_preimport_repeater_plugin(monkeypatch: pytest.MonkeyPatch):
    from pallas.core.platform.ai_callback import http as callback_http
    from pallas.core.platform.bot_runtime import kernel_runtime

    monkeypatch.setenv("PALLAS_SHARD_ENABLED", "true")
    monkeypatch.setenv("PALLAS_BOT_ROLE", "worker")
    get_shard_registry_settings.cache_clear()

    kernel_runtime._KERNEL_REGISTERED = False
    callback_http._http_registered = False
    for name in list(sys.modules):
        if name == "packages.repeater" or name.startswith("packages.repeater."):
            sys.modules.pop(name, None)

    nonebot.init()
    kernel_runtime.register_kernel_runtime()

    assert "packages.repeater" not in sys.modules


def test_register_kernel_runtime_does_not_preimport_pb_webui_plugin(monkeypatch: pytest.MonkeyPatch):
    from pallas.core.platform.ai_callback import http as callback_http
    from pallas.core.platform.bot_runtime import kernel_runtime

    monkeypatch.setenv("PALLAS_SHARD_ENABLED", "true")
    monkeypatch.setenv("PALLAS_BOT_ROLE", "hub")
    get_shard_registry_settings.cache_clear()

    kernel_runtime._KERNEL_REGISTERED = False
    callback_http._http_registered = False
    for name in list(sys.modules):
        if name == "packages.pb_webui" or name.startswith("packages.pb_webui."):
            sys.modules.pop(name, None)

    nonebot.init()
    kernel_runtime.register_kernel_runtime()

    assert "packages.pb_webui" not in sys.modules


def test_register_worker_console_metrics_only_on_worker(monkeypatch: pytest.MonkeyPatch):
    from pallas.core.platform.shard import worker_console_metrics as wcm

    monkeypatch.setenv("PALLAS_SHARD_ENABLED", "true")
    monkeypatch.setenv("PALLAS_BOT_ROLE", "hub")
    get_shard_registry_settings.cache_clear()
    wcm._registered = False
    wcm.register_worker_console_metrics_startup()
    assert wcm._registered is False

    monkeypatch.setenv("PALLAS_BOT_ROLE", "worker")
    get_shard_registry_settings.cache_clear()
    nonebot.init()
    wcm._registered = False
    wcm.register_worker_console_metrics_startup()
    assert wcm._registered is True
