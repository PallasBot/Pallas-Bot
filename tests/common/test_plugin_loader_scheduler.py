from __future__ import annotations

import sys
import types

import nonebot

from pallas.core.platform.bot_runtime.plugin_loader import (
    _prioritize_scheduler_modules,
    clear_poisoned_apscheduler_import,
    load_apscheduler_plugin_first,
)


def test_prioritize_scheduler_modules_puts_apscheduler_first():
    paths = ["my_pack", "nonebot_plugin_apscheduler", "other"]
    assert _prioritize_scheduler_modules(paths) == [
        "nonebot_plugin_apscheduler",
        "my_pack",
        "other",
    ]


def test_clear_poisoned_apscheduler_import_removes_unregistered_module():
    stub = types.ModuleType("nonebot_plugin_apscheduler")
    sys.modules["nonebot_plugin_apscheduler"] = stub
    try:
        assert clear_poisoned_apscheduler_import(role_label="test") is True
        assert "nonebot_plugin_apscheduler" not in sys.modules
    finally:
        sys.modules.pop("nonebot_plugin_apscheduler", None)


def test_load_apscheduler_plugin_first_recovers_from_poisoned_preimport():
    nonebot.init()
    stub = types.ModuleType("nonebot_plugin_apscheduler")
    sys.modules["nonebot_plugin_apscheduler"] = stub
    loaded_short: set[str] = set()
    try:
        assert load_apscheduler_plugin_first(role_label="test", loaded_short=loaded_short) is True
        module = sys.modules.get("nonebot_plugin_apscheduler")
        assert module is not None
        assert getattr(module, "__plugin__", None) is not None
    finally:
        sys.modules.pop("nonebot_plugin_apscheduler", None)
        for name in list(sys.modules):
            if name.startswith("nonebot_plugin_apscheduler."):
                sys.modules.pop(name, None)
