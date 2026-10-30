from types import SimpleNamespace

import pytest
from fastapi import FastAPI


@pytest.mark.parametrize(
    ("enabled", "hub", "expected"), [(True, False, True), (False, False, False), (True, True, False)]
)
def test_kernel_registers_native_control_only_for_enabled_message_runtime(monkeypatch, enabled, hub, expected):
    from pallas.core.platform.bot_runtime import kernel_runtime

    app = FastAPI()
    monkeypatch.setattr("nonebot.get_app", lambda: app)
    monkeypatch.setattr(
        "pallas.product.agent_bridge.config.load_bridge_config",
        lambda: SimpleNamespace(enabled=enabled),
    )
    monkeypatch.setattr(kernel_runtime, "_KERNEL_REGISTERED", False)
    monkeypatch.setattr(kernel_runtime, "is_hub_role", lambda: hub)
    callback_calls = []
    monkeypatch.setattr(kernel_runtime, "register_ai_callback_http", lambda: callback_calls.append("registered"))
    runtime_calls = []
    monkeypatch.setattr(
        kernel_runtime,
        "register_bot_filter_runtime",
        lambda: runtime_calls.append("register_bot_filter_runtime"),
    )
    for target in (
        "pallas.core.platform.ingress.gate.register_ingress_gate_runtime",
        "pallas.core.platform.ingress.message_recorder.bind_message_recorder_lifecycle",
        "pallas.core.platform.bot_runtime.ingress_dispatch_runtime.register_ingress_dispatch_runtime",
        "pallas.product.service_gateways.runtime.register_service_gateways_runtime",
        "pallas.core.platform.bot_runtime.kernel_runtime.register_duplicate_prefix_startup_check",
        "pallas.product.llm.silence_gate.register_silence_gate_runtime",
    ):
        monkeypatch.setattr(target, lambda target=target: runtime_calls.append(target))

    kernel_runtime.register_kernel_runtime()
    kernel_runtime.register_kernel_runtime()
    paths = [getattr(route, "path", "") for route in app.routes]
    control_prefix = "/pallas/api/internal/maibot/control"
    for endpoint in ("status", "quiesce"):
        assert paths.count(f"{control_prefix}/{endpoint}") == int(expected)
    assert not any(path.startswith("/pallas/api/internal/maibot/provider") for path in paths)
    assert bool(getattr(app.state, "_pallas_ai_boundary_guard", False)) is expected
    assert callback_calls == ["registered"]
    assert len(runtime_calls) == (0 if hub else 7)
