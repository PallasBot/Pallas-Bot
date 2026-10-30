"""Private control surface for MaiBot's native-managed runtime."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from fastapi import Request  # noqa: TC002
from fastapi.responses import JSONResponse

from pallas.core.platform.ai_callback.boundary_guard import install_ai_boundary_guard
from pallas.core.platform.ai_callback.internal_auth import (
    INTERNAL_TOKEN_HEADER,
    PURPOSE_MAIBOT_CONTROL_V1,
    verify_internal_token,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

_PATH = "/pallas/api/internal/maibot/control"


@dataclass(slots=True)
class ManagedControlState:
    runtime_id: str = field(default_factory=lambda: uuid4().hex)
    quiesced: bool = False


def _auth_ok(request: Request) -> bool:
    key = INTERNAL_TOKEN_HEADER.lower().encode("latin-1")
    values = [value.decode("latin-1") for name, value in request.scope.get("headers", []) if name.lower() == key]
    return len(values) == 1 and verify_internal_token(PURPOSE_MAIBOT_CONTROL_V1, values[0])


def _error(code: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "retryable": False}}


def _status_snapshot(state: ManagedControlState) -> dict[str, Any]:
    from pallas.product.agent_bridge import runtime

    bridge = runtime.bridge_status()
    quiesced = state.quiesced or bridge["state"] == "quiesced"
    connected = bridge["connected"] is True and bridge["state"] == "connected"
    return {
        "ok": True,
        "runtime_id": state.runtime_id,
        "contract": "maibot-native-control-v1",
        "control_ready": True,
        "bridge_status": bridge,
        "component_ready": connected and not quiesced,
        "complete_ready": False,
        "readiness_scope": "managed-component",
        "model_invocation_verified": False,
        "quiesced": quiesced,
    }


def register_managed_control_http(app: FastAPI) -> ManagedControlState:
    existing = getattr(app.state, "maibot_managed_control", None)
    if isinstance(existing, ManagedControlState):
        return existing
    install_ai_boundary_guard(app)
    if not getattr(app.state, "_pallas_ai_boundary_guard", False):
        raise RuntimeError("AI boundary guard must be installed before MaiBot control registration")

    state = ManagedControlState()
    app.state.maibot_managed_control = state

    @app.get(f"{_PATH}/status")
    async def managed_status(request: Request) -> JSONResponse:
        if not _auth_ok(request):
            return JSONResponse({"detail": "unauthorized"}, status_code=403)
        return JSONResponse(_status_snapshot(state))

    @app.post(f"{_PATH}/quiesce")
    async def managed_quiesce(request: Request) -> JSONResponse:
        if not _auth_ok(request):
            return JSONResponse({"detail": "unauthorized"}, status_code=403)
        if await request.body():
            return JSONResponse(_error("invalid_request"), status_code=400)
        from pallas.product.agent_bridge import runtime

        try:
            await runtime.quiesce_bridge()
        except asyncio.CancelledError:
            raise
        except Exception:
            return JSONResponse(_error("control_failed"), status_code=503)
        state.quiesced = True
        return JSONResponse({"ok": True, "quiesced": True})

    return state
