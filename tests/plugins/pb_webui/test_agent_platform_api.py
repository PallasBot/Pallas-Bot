from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from packages.pb_webui.agent_platform_api import register_agent_platform_router


def _client() -> TestClient:
    app = FastAPI()
    router = APIRouter()
    register_agent_platform_router(
        router,
        x="/pallas/api",
        plugin_config=object(),
        check_write_token=lambda *_args, **_kwargs: None,
    )
    app.include_router(router)
    return TestClient(app)
