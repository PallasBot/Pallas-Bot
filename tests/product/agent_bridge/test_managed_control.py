from __future__ import annotations

import asyncio

import httpx
import pytest
from aiohttp import web
from fastapi import FastAPI
from starlette.testclient import TestClient

from pallas.core.platform.ai_callback import internal_auth
from pallas.product.agent_bridge.managed_control import register_managed_control_http

_PATH = "/pallas/api/internal/maibot/control"


@pytest.fixture(autouse=True)
def isolate_data_root(monkeypatch: pytest.MonkeyPatch, tmp_path):
    from pallas.core.foundation import paths

    monkeypatch.setattr(paths, "DATA_ROOT", tmp_path / "data")


def _control_headers() -> dict[str, str]:
    return {
        internal_auth.INTERNAL_TOKEN_HEADER: internal_auth.derive_internal_token(
            internal_auth.PURPOSE_MAIBOT_CONTROL_V1
        )
    }


def test_status_is_native_control_only_and_runtime_id_is_app_scoped(monkeypatch):
    from pallas.product.agent_bridge import runtime

    bridge = {"connected": True, "state": "connected"}
    monkeypatch.setattr(runtime, "bridge_status", lambda: bridge)
    app = FastAPI()
    state = register_managed_control_http(app)
    assert register_managed_control_http(app) is state
    other_state = register_managed_control_http(FastAPI())
    assert state.runtime_id == app.state.maibot_managed_control.runtime_id
    assert state.runtime_id != other_state.runtime_id
    assert not hasattr(app.state, "maibot_provider_http")

    with TestClient(app) as client:
        response = client.get(f"{_PATH}/status", headers=_control_headers())
    assert response.status_code == 200
    status = response.json()
    assert set(status) == {
        "ok",
        "runtime_id",
        "contract",
        "control_ready",
        "bridge_status",
        "component_ready",
        "complete_ready",
        "readiness_scope",
        "model_invocation_verified",
        "quiesced",
    }
    assert status == {
        "ok": True,
        "runtime_id": state.runtime_id,
        "contract": "maibot-native-control-v1",
        "control_ready": True,
        "bridge_status": bridge,
        "component_ready": True,
        "complete_ready": False,
        "readiness_scope": "managed-component",
        "model_invocation_verified": False,
        "quiesced": False,
    }
    bridge["state"] = "reconnecting"
    with TestClient(app) as client:
        assert client.get(f"{_PATH}/status", headers=_control_headers()).json()["component_ready"] is False


def test_quiesce_requires_control_auth_empty_bounded_body_and_is_idempotent(monkeypatch):
    from pallas.product.agent_bridge import runtime

    app = FastAPI()
    state = register_managed_control_http(app)
    calls = 0

    async def quiesce():
        nonlocal calls
        calls += 1

    monkeypatch.setattr(runtime, "quiesce_bridge", quiesce)
    control_token = internal_auth.derive_internal_token(internal_auth.PURPOSE_MAIBOT_CONTROL_V1)
    other_token = internal_auth.derive_internal_token(internal_auth.PURPOSE_AI_TASK_REGISTRATION)
    with TestClient(app) as client:
        assert client.post(f"{_PATH}/quiesce").status_code == 403
        assert (
            client.post(
                f"{_PATH}/quiesce",
                headers={internal_auth.INTERNAL_TOKEN_HEADER: other_token},
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"{_PATH}/quiesce",
                content=b"{}",
                headers={internal_auth.INTERNAL_TOKEN_HEADER: control_token},
            ).status_code
            == 400
        )
        assert (
            client.post(
                f"{_PATH}/quiesce",
                content=b"x" * (2 * 1024 + 1),
                headers={internal_auth.INTERNAL_TOKEN_HEADER: control_token},
            ).status_code
            == 413
        )
        duplicate_headers = [
            (internal_auth.INTERNAL_TOKEN_HEADER, control_token),
            (internal_auth.INTERNAL_TOKEN_HEADER, control_token),
        ]
        assert client.post(f"{_PATH}/quiesce", headers=duplicate_headers).status_code == 400
        assert calls == 0

        first = client.post(
            f"{_PATH}/quiesce",
            headers={internal_auth.INTERNAL_TOKEN_HEADER: control_token},
        )
        second = client.post(
            f"{_PATH}/quiesce",
            headers={internal_auth.INTERNAL_TOKEN_HEADER: control_token},
        )
    assert first.json() == second.json() == {"ok": True, "quiesced": True}
    assert calls == 2
    assert state.quiesced is True


@pytest.mark.asyncio
async def test_status_and_quiesce_follow_real_bridge_websocket_state(monkeypatch):
    from pallas.product.agent_bridge import runtime
    from pallas.product.agent_bridge.config import MaiBotBridgeConfig

    app = FastAPI()
    state = register_managed_control_http(app)
    accepted = asyncio.Event()

    async def ws_handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        accepted.set()
        async for _message in ws:
            pass
        return ws

    ws_app = web.Application()
    ws_app.router.add_get("/ws", ws_handler)
    ws_runner = web.AppRunner(ws_app)
    await ws_runner.setup()
    site = web.TCPSite(ws_runner, "127.0.0.1", 0)
    await site.start()
    config = MaiBotBridgeConfig(
        enabled=True,
        url=f"ws://127.0.0.1:{ws_runner.addresses[0][1]}/ws",
        bot_id=10001,
        group_ids=frozenset({700001}),
        platform="pallas-qq",
        token="",
    )
    monkeypatch.setattr(runtime, "load_bridge_config", lambda: config)
    monkeypatch.setattr(runtime, "_live_config_or_none", lambda: config)

    try:
        assert await runtime.start_bridge() is True
        assert await runtime.wait_bridge_ready(timeout=1) is True
        await asyncio.wait_for(accepted.wait(), 1)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            before = (await client.get(f"{_PATH}/status", headers=_control_headers())).json()
            assert before["component_ready"] is True
            assert before["bridge_status"]["connected"] is True
            assert before["bridge_status"]["state"] == "connected"
            assert before["runtime_id"] == state.runtime_id

            result = await client.post(f"{_PATH}/quiesce", headers=_control_headers())
            assert result.json() == {"ok": True, "quiesced": True}
            after = (await client.get(f"{_PATH}/status", headers=_control_headers())).json()
            assert after["bridge_status"]["connected"] is False
            assert after["bridge_status"]["state"] == "quiesced"
            assert after["component_ready"] is False
            assert after["quiesced"] is True
            assert after["control_ready"] is True
            assert after["complete_ready"] is False
        assert runtime.bridge_owns(10001, 700001) is True
    finally:
        await runtime.stop_bridge()
        await ws_runner.cleanup()
