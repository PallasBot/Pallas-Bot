from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from packages.pb_webui.agent_platform_api import register_agent_platform_router
from pallas.product.persona.catchphrase_bank import CatchphraseEntry


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


def test_catchphrases_list_filters_and_pages_results(monkeypatch) -> None:
    rows = [
        CatchphraseEntry(entry_id="candidate-1", bot_id=1, saying="甲", status="candidate"),
        CatchphraseEntry(entry_id="active-1", bot_id=1, saying="乙", status="active"),
        CatchphraseEntry(entry_id="candidate-2", bot_id=1, saying="丙", status="candidate"),
        CatchphraseEntry(entry_id="candidate-3", bot_id=1, saying="丁", status="candidate"),
    ]
    monkeypatch.setattr("pallas.product.persona.catchphrase_bank.list_catchphrases", lambda *_args, **_kwargs: rows)

    response = _client().get("/pallas/api/llm/agent-platform/catchphrases?bot_id=1&status=candidate&offset=1&limit=1")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert [item["entry_id"] for item in data["items"]] == ["candidate-2"]
    assert data["count"] == 1
    assert data["total"] == 3
    assert data["counts"] == {"candidate": 3, "active": 1, "all": 4}
