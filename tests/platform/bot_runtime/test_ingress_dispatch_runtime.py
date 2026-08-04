from __future__ import annotations

import pytest

from pallas.core.platform.bot_runtime import ingress_dispatch_runtime as runtime


def test_register_skips_hub(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "_HOOK_REGISTERED", False)
    monkeypatch.setattr(runtime, "is_hub_role", lambda: True)
    runtime.register_ingress_dispatch_runtime()
    assert runtime.ingress_dispatch_runtime_registered() is False


def test_register_unified(monkeypatch) -> None:
    import nonebot

    nonebot.init()
    monkeypatch.setattr(runtime, "_HOOK_REGISTERED", False)
    monkeypatch.setattr(runtime, "is_hub_role", lambda: False)
    runtime.register_ingress_dispatch_runtime()
    assert runtime.ingress_dispatch_runtime_registered() is True


@pytest.mark.asyncio
async def test_runtime_starts_and_stops_conversation_scheduler_in_order(monkeypatch) -> None:
    class Driver:
        startup = None
        shutdown = None

        def on_startup(self, callback):
            self.startup = callback
            return callback

        def on_shutdown(self, callback):
            self.shutdown = callback
            return callback

    driver = Driver()
    events: list[str] = []

    async def record_async(name: str) -> None:
        events.append(name)

    monkeypatch.setattr(runtime, "_HOOK_REGISTERED", False)
    monkeypatch.setattr(runtime, "is_hub_role", lambda: False)
    monkeypatch.setattr(runtime, "get_driver", lambda: driver)
    monkeypatch.setattr(runtime, "route_index_enabled", lambda: False)
    monkeypatch.setattr(runtime, "install_send_queue", lambda: events.append("install_send"))
    monkeypatch.setattr(runtime, "start_send_queue_workers", lambda: record_async("start_send"))
    monkeypatch.setattr(runtime, "start_conversation_scheduler", lambda: record_async("start_scheduler"))
    monkeypatch.setattr(runtime, "install_matcher_dispatch", lambda: events.append("install_matcher"))
    monkeypatch.setattr(runtime, "start_dispatch_stats_logger", lambda: events.append("start_stats"))
    monkeypatch.setattr(runtime, "stop_dispatch_stats_logger", lambda: record_async("stop_stats"))
    monkeypatch.setattr(runtime, "stop_conversation_scheduler", lambda: record_async("stop_scheduler"))
    monkeypatch.setattr(runtime, "uninstall_matcher_dispatch", lambda: events.append("uninstall_matcher"))
    monkeypatch.setattr(runtime, "stop_send_queue_workers", lambda: record_async("stop_send"))
    monkeypatch.setattr(runtime, "uninstall_send_queue", lambda: events.append("uninstall_send"))
    monkeypatch.setattr(runtime, "matcher_dispatch_enabled", lambda: False)

    runtime.register_ingress_dispatch_runtime()
    assert driver.startup is not None
    assert driver.shutdown is not None

    await driver.startup()
    await driver.shutdown()

    assert events == [
        "install_send",
        "start_send",
        "start_scheduler",
        "install_matcher",
        "start_stats",
        "stop_stats",
        "stop_scheduler",
        "uninstall_matcher",
        "stop_send",
        "uninstall_send",
    ]
