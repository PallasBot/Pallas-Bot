from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from packages.pb_webui.config import Config
from packages.pb_webui.logs_api import register_logs_router


def test_logs_api_lists_available_aux_sources(monkeypatch):
    monkeypatch.setattr("packages.pb_webui.logs_api._ensure_log_sink", lambda: None)
    monkeypatch.setattr("packages.pb_webui.logs_api.shard_hub_console", lambda: False)
    monkeypatch.setattr("pallas.console.web.list_aux_log_sources", lambda: ["work", "embed"])
    monkeypatch.setattr("pallas.console.web.tail_nonebot_log_lines_scoped", lambda *_a, **_kw: [])
    monkeypatch.setattr("pallas.console.web.tail_nonebot_log_entries_scoped", lambda *_a, **_kw: [])

    app = FastAPI()
    router = APIRouter()
    register_logs_router(router, x="/pallas/api", plugin_config=Config())
    app.include_router(router)

    response = TestClient(app).get("/pallas/api/logs")

    assert response.status_code == 200
    assert response.json()["data"]["log_sources"] == ["hub", "work", "embed"]
