from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.routing import _IncludedRouter

from packages.pb_webui import extended_api as mod
from packages.pb_webui.config import Config


def _find_console_route_endpoint(app: FastAPI, path: str):
    """FastAPI 0.141 include_router 把路由包进 _IncludedRouter，需展开查找。"""

    def _walk(routes):
        for route in routes:
            if isinstance(route, _IncludedRouter):
                yield from _walk(route.effective_candidates())
            else:
                yield route

    for candidate in _walk(app.routes):
        if getattr(candidate, "path", "") == path:
            return getattr(candidate, "endpoint", None)
    raise LookupError(path)


def test_persona_export_endpoint_only_accepts_current_parameters(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_check_pallas_write_token", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_require_pallas_token_configured", lambda *a, **k: None)
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    app = FastAPI()
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())

    operation = app.openapi()["paths"]["/pallas/api/common-config/llm/persona/export"]["get"]
    names = {item["name"] for item in operation["parameters"]}

    assert names == {"bot_id", "group_id", "plain_text", "mode", "token", "X-Pallas-Token", "X-Pallas-Api-Key"}


@pytest.mark.asyncio
async def test_persona_export_endpoint_forwards_current_parameters(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_check_pallas_write_token", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_require_pallas_token_configured", lambda *a, **k: None)
    monkeypatch.setattr(mod, "ensure_console_metrics_hooks", lambda: None)
    calls = []

    async def build_bundle(bot_id, group_id, plain_text, *, mode):
        calls.append((bot_id, group_id, plain_text, mode))
        return SimpleNamespace(model_dump=lambda: {"purpose": "chat"})

    monkeypatch.setattr(
        "pallas.product.persona.bundle_export.build_persona_asset_bundle_v1",
        build_bundle,
    )
    app = FastAPI()
    mod.register_extended_api(app, api_base="/pallas/api", plugin_config=Config())
    endpoint = _find_console_route_endpoint(app, "/pallas/api/common-config/llm/persona/export")
    response = await endpoint(bot_id=10, group_id=20, plain_text="test", mode="normal")

    assert response.status_code == 200
    assert b'"purpose":"chat"' in response.body
    assert calls == [(10, 20, "test", "normal")]
