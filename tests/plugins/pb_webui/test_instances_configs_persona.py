from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from packages.pb_webui.config import Config
from packages.pb_webui.instances_configs_api import (
    _apply_bot_config_patch,
    _BotConfigPatch,
    register_instances_configs_router,
)


@pytest.mark.asyncio
async def test_bot_persona_patch_merges_before_single_upsert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incoming = {"account_profile": {"source": "manual", "warmth": 0.5}}

    class Repo:
        def __init__(self) -> None:
            self.persona = {
                "seed": {"prefs": ["warm"]},
                "self_aliases": ["猪猪"],
                "peer_aliases": ["隔壁牛"],
                "future_field": {"enabled": True},
            }
            self.upserts: list[dict] = []

        async def get_or_create(self, account, **defaults):  # noqa: ARG002
            return None, False

        async def get(self, account, ignore_cache=False):  # noqa: ARG002
            return type(
                "BotConfig",
                (),
                {
                    "account": account,
                    "admins": [],
                    "disabled_plugins": [],
                    "taken_name": {},
                    "drunk": {},
                    "persona": deepcopy(self.persona),
                },
            )()

        async def upsert_fields(self, account, fields):  # noqa: ARG002
            self.upserts.append(deepcopy(fields))
            if "persona" in fields:
                self.persona = deepcopy(fields["persona"])

    repo = Repo()
    monkeypatch.setattr("pallas.core.foundation.db.make_bot_config_repository", lambda: repo)

    result = await _apply_bot_config_patch(7, _BotConfigPatch(persona=incoming))

    assert len(repo.upserts) == 1
    persisted = repo.upserts[0]["persona"]
    assert persisted["account_profile"]["source"] == "manual"
    assert persisted["account_profile"]["warmth"] == 0.5
    assert persisted["seed"] == {"prefs": ["warm"]}
    assert persisted["self_aliases"] == ["猪猪"]
    assert persisted["peer_aliases"] == ["隔壁牛"]
    assert persisted["future_field"] == {"enabled": True}
    assert result["persona"] == persisted


@pytest.mark.parametrize(
    "account_profile",
    [
        ["not", "an", "object"],
        {"source": "manual", "energy": 2.0},
        {"source": "manual", "energy": 0.1, "warmth": 0.2, "mischief": 0.3},
        {"source": "unknown", "warmth": 0.2},
    ],
)
@pytest.mark.asyncio
async def test_bot_persona_endpoint_rejects_invalid_account_profile(
    monkeypatch: pytest.MonkeyPatch,
    account_profile: object,
) -> None:
    from packages.pb_webui import instances_configs_api as api

    monkeypatch.setattr(api, "check_pallas_write_token", lambda *args, **kwargs: None)
    app = FastAPI()
    register_instances_configs_router(app.router, x="/pallas/api", plugin_config=Config())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            "/pallas/api/bot-configs/7",
            json={"persona": {"account_profile": account_profile}},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_bot_persona_endpoint_removes_profile_without_losing_other_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.pb_webui import instances_configs_api as api

    class Repo:
        def __init__(self) -> None:
            self.persona = {
                "account_profile": {"source": "manual", "warmth": 0.5},
                "seed": {"prefs": ["warm"]},
                "self_aliases": ["猪猪"],
                "peer_aliases": ["隔壁牛"],
            }
            self.upserts: list[dict] = []

        async def get_or_create(self, account, **defaults):  # noqa: ARG002
            return None, False

        async def get(self, account, ignore_cache=False):  # noqa: ARG002
            return type(
                "BotConfig",
                (),
                {
                    "account": account,
                    "admins": [],
                    "disabled_plugins": [],
                    "taken_name": {},
                    "drunk": {},
                    "persona": deepcopy(self.persona),
                },
            )()

        async def upsert_fields(self, account, fields):  # noqa: ARG002
            self.upserts.append(deepcopy(fields))
            self.persona = deepcopy(fields["persona"])

    repo = Repo()
    monkeypatch.setattr(api, "check_pallas_write_token", lambda *args, **kwargs: None)
    monkeypatch.setattr("pallas.core.foundation.db.make_bot_config_repository", lambda: repo)
    app = FastAPI()
    register_instances_configs_router(app.router, x="/pallas/api", plugin_config=Config())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            "/pallas/api/bot-configs/7",
            json={"persona": {"account_profile": None}},
        )

    assert response.status_code == 200
    assert len(repo.upserts) == 1
    persisted = repo.upserts[0]["persona"]
    assert "account_profile" not in persisted
    assert persisted["seed"] == {"prefs": ["warm"]}
    assert persisted["self_aliases"] == ["猪猪"]
    assert persisted["peer_aliases"] == ["隔壁牛"]


@pytest.mark.parametrize("retired_field", ["seed"])
@pytest.mark.asyncio
async def test_bot_persona_endpoint_rejects_retired_editor_fields(
    monkeypatch: pytest.MonkeyPatch,
    retired_field: str,
) -> None:
    from packages.pb_webui import instances_configs_api as api

    monkeypatch.setattr(api, "check_pallas_write_token", lambda *args, **kwargs: None)
    app = FastAPI()
    register_instances_configs_router(app.router, x="/pallas/api", plugin_config=Config())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            "/pallas/api/bot-configs/7",
            json={"persona": {retired_field: {}}},
        )

    assert response.status_code == 422


@pytest.mark.parametrize("open_field", ["disposition", "seed_override"])
@pytest.mark.asyncio
async def test_bot_persona_endpoint_accepts_seed_and_disposition(
    monkeypatch: pytest.MonkeyPatch,
    open_field: str,
) -> None:
    from packages.pb_webui import instances_configs_api as api

    class Repo:
        def __init__(self) -> None:
            self.persona = {"self_aliases": ["猪猪"]}
            self.upserts: list[dict] = []

        async def get_or_create(self, account, **defaults):  # noqa: ARG002
            return None, False

        async def get(self, account, ignore_cache=False):  # noqa: ARG002
            return type(
                "BotConfig",
                (),
                {
                    "account": account,
                    "admins": [],
                    "disabled_plugins": [],
                    "taken_name": {},
                    "drunk": {},
                    "persona": deepcopy(self.persona),
                },
            )()

        async def upsert_fields(self, account, fields):  # noqa: ARG002
            self.upserts.append(deepcopy(fields))
            self.persona = deepcopy(fields["persona"])

    repo = Repo()
    monkeypatch.setattr(api, "check_pallas_write_token", lambda *args, **kwargs: None)
    monkeypatch.setattr("pallas.core.foundation.db.make_bot_config_repository", lambda: repo)
    app = FastAPI()
    register_instances_configs_router(app.router, x="/pallas/api", plugin_config=Config())

    payload = {"persona": {}}
    if open_field == "disposition":
        payload["persona"]["disposition"] = {"approach": "先接住对方情绪再给结论"}
    else:
        payload["persona"]["seed_override"] = {"prefs": ["chaotic"]}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put("/pallas/api/bot-configs/7", json=payload)

    assert response.status_code == 200
    assert len(repo.upserts) == 1
    persisted = repo.upserts[0]["persona"]
    if open_field == "disposition":
        assert persisted["disposition"]["approach"] == "先接住对方情绪再给结论"
    else:
        assert persisted["seed_override"]["prefs"] == ["chaotic"]


def test_bot_persona_openapi_uses_typed_account_profile() -> None:
    app = FastAPI()
    register_instances_configs_router(app.router, x="/pallas/api", plugin_config=Config())

    schema = app.openapi()
    patch_schema = schema["components"]["schemas"]["_BotConfigPatch"]
    persona_ref = patch_schema["properties"]["persona"]["anyOf"][0]["$ref"]
    persona_schema = schema["components"]["schemas"][persona_ref.rsplit("/", 1)[-1]]

    assert set(persona_schema["properties"]) == {"account_profile", "disposition", "seed_override"}
