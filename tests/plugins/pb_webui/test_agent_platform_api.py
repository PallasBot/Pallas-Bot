from __future__ import annotations

import pytest
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


def test_person_facts_api_lists_saves_and_corrects(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.memory.person_facts._store_path",
        lambda: tmp_path / "person_facts.json",
    )
    client = _client()

    saved = client.post(
        "/pallas/api/llm/agent-platform/person-facts",
        json={"bot_id": 1, "group_id": 2, "user_id": 3, "content": "likes cats"},
    )
    assert saved.status_code == 200
    fact_id = saved.json()["data"]["fact_id"]

    listed = client.get("/pallas/api/llm/agent-platform/person-facts?bot_id=1&group_id=2&user_id=3")
    assert listed.status_code == 200
    assert listed.json()["data"]["items"][0]["content"] == "likes cats"

    corrected = client.post(
        "/pallas/api/llm/agent-platform/person-facts/correct",
        json={"fact_id": fact_id, "content": "likes dogs"},
    )
    assert corrected.status_code == 200
    assert corrected.json()["data"]["content"] == "likes dogs"


@pytest.mark.parametrize(
    ("route", "payload"),
    [
        (
            "/pallas/api/llm/agent-platform/person-facts",
            {"bot_id": 1, "group_id": 2, "user_id": 3, "content": "new fact"},
        ),
        (
            "/pallas/api/llm/agent-platform/person-facts/correct",
            {"fact_id": "missing", "content": "new fact"},
        ),
    ],
)
def test_person_facts_api_preserves_corrupt_store_on_write(monkeypatch, tmp_path, route, payload) -> None:
    store_path = tmp_path / "person_facts.json"
    original = b'{"items": [broken]}'
    store_path.write_bytes(original)
    monkeypatch.setattr("pallas.product.llm.memory.person_facts._store_path", lambda: store_path)

    response = _client().post(route, json=payload)

    assert response.status_code == 400
    assert store_path.read_bytes() == original
