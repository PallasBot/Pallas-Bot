from __future__ import annotations

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
