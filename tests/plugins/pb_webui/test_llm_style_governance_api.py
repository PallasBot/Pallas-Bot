from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from packages.pb_webui.config import Config
from packages.pb_webui.llm_ops_api import register_llm_ops_router


class DummyGroupRepo:
    def __init__(self) -> None:
        self.upserts: list[tuple[int, str, object]] = []

    async def get(self, key_id: int, *, ignore_cache: bool = False):
        return None

    async def upsert_field(self, key_id: int, field: str, value):
        self.upserts.append((key_id, field, value))


def _make_app(monkeypatch, tmp_path, *, check_write_token=lambda *a, **k: None) -> tuple[FastAPI, DummyGroupRepo]:
    from pallas.product.persona import base_prompt_override as overrides
    from pallas.product.persona import style_governance as governance

    monkeypatch.setattr(governance, "group_style_governance_path", lambda: tmp_path / "governance.json")
    monkeypatch.setattr(overrides, "base_prompt_override_path", lambda: tmp_path / "base_prompt_override.json")
    repo = DummyGroupRepo()
    monkeypatch.setattr(governance, "make_group_config_repository", lambda: repo)
    monkeypatch.setattr(governance, "invalidate_persona_cache", lambda bot_id=None: None)
    app = FastAPI()
    register_llm_ops_router(app.router, x="/pallas/api", plugin_config=Config(), check_write_token=check_write_token)
    return app, repo


async def _client(monkeypatch, tmp_path, **kwargs):
    app, repo = _make_app(monkeypatch, tmp_path, **kwargs)
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return client, repo


GROUP_STYLE_MANAGE = "/pallas/api/common-config/llm/persona/group-style/manage"
BASE_PROMPT = "/pallas/api/common-config/llm/persona/base-prompt"


@pytest.mark.asyncio
async def test_group_style_manage_get_status_defaults_enabled(monkeypatch, tmp_path) -> None:
    client, _ = await _client(monkeypatch, tmp_path)
    async with client:
        response = await client.get(GROUP_STYLE_MANAGE, params={"bot_id": 100, "group_id": 42})

    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "data": {"collection_enabled": True, "injection_enabled": True}}


@pytest.mark.asyncio
async def test_group_style_manage_get_requires_both_scope(monkeypatch, tmp_path) -> None:
    client, _ = await _client(monkeypatch, tmp_path)
    async with client:
        response = await client.get(GROUP_STYLE_MANAGE, params={"bot_id": 100})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_group_style_manage_collection_toggle(monkeypatch, tmp_path) -> None:
    client, _ = await _client(monkeypatch, tmp_path)
    async with client:
        off = await client.post(
            GROUP_STYLE_MANAGE,
            json={"bot_id": 100, "group_id": 42, "action": "collection", "enabled": False},
        )
        status = await client.get(GROUP_STYLE_MANAGE, params={"bot_id": 100, "group_id": 42})

    assert off.status_code == 200, off.text
    assert off.json()["data"]["collection_enabled"] is False
    assert status.json()["data"] == {"collection_enabled": False, "injection_enabled": True}


@pytest.mark.asyncio
async def test_group_style_manage_injection_toggle(monkeypatch, tmp_path) -> None:
    client, _ = await _client(monkeypatch, tmp_path)
    async with client:
        off = await client.post(
            GROUP_STYLE_MANAGE,
            json={"bot_id": 100, "group_id": 42, "action": "injection", "enabled": False},
        )
        status = await client.get(GROUP_STYLE_MANAGE, params={"bot_id": 100, "group_id": 42})

    assert off.status_code == 200, off.text
    assert off.json()["data"]["injection_enabled"] is False
    assert status.json()["data"]["injection_enabled"] is False
    assert status.json()["data"]["collection_enabled"] is True


@pytest.mark.asyncio
async def test_group_style_manage_clear_pauses_when_not_learning(monkeypatch, tmp_path) -> None:
    client, repo = await _client(monkeypatch, tmp_path)
    async with client:
        response = await client.post(
            GROUP_STYLE_MANAGE,
            json={"bot_id": 100, "group_id": 42, "action": "clear", "continue_learning": False},
        )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["collection_enabled"] is False
    assert data["injection_enabled"] is False
    assert repo.upserts == [(42, "style_profile", None)]


@pytest.mark.asyncio
async def test_group_style_manage_clear_resumes_learning(monkeypatch, tmp_path) -> None:
    client, _ = await _client(monkeypatch, tmp_path)
    async with client:
        await client.post(
            GROUP_STYLE_MANAGE,
            json={"bot_id": 100, "group_id": 42, "action": "collection", "enabled": False},
        )
        cleared = await client.post(
            GROUP_STYLE_MANAGE,
            json={"bot_id": 100, "group_id": 42, "action": "clear", "continue_learning": True},
        )

    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["data"]["collection_enabled"] is True


@pytest.mark.asyncio
async def test_group_style_manage_collection_requires_enabled(monkeypatch, tmp_path) -> None:
    client, _ = await _client(monkeypatch, tmp_path)
    async with client:
        response = await client.post(
            GROUP_STYLE_MANAGE,
            json={"bot_id": 100, "group_id": 42, "action": "collection"},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_group_style_manage_post_requires_write_token(monkeypatch, tmp_path) -> None:
    def _deny(*args, **kwargs):
        raise HTTPException(status_code=401, detail="denied")

    client, _ = await _client(monkeypatch, tmp_path, check_write_token=_deny)
    async with client:
        response = await client.post(
            GROUP_STYLE_MANAGE,
            json={"bot_id": 100, "group_id": 42, "action": "collection", "enabled": True},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_base_prompt_get_preview_summary_when_absent(monkeypatch, tmp_path) -> None:
    client, _ = await _client(monkeypatch, tmp_path)
    async with client:
        response = await client.get(BASE_PROMPT)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["enabled"] is False
    assert data["mode"] == "append"
    assert data["text_preview"] == ""
    assert "text" not in data


@pytest.mark.asyncio
async def test_base_prompt_save_append_and_get_preview(monkeypatch, tmp_path) -> None:
    client, _ = await _client(monkeypatch, tmp_path)
    async with client:
        saved = await client.post(f"{BASE_PROMPT}/save", json={"mode": "append", "text": "本群直呼昵称"})
        status = await client.get(BASE_PROMPT)

    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["mode"] == "append"
    assert saved.json()["data"]["text"] == "本群直呼昵称"
    data = status.json()["data"]
    assert data["enabled"] is True
    assert data["mode"] == "append"
    assert data["text_preview"] == "本群直呼昵称"


@pytest.mark.asyncio
async def test_base_prompt_content_returns_raw_text_with_write_token(monkeypatch, tmp_path) -> None:
    client, _ = await _client(monkeypatch, tmp_path)
    async with client:
        await client.post(f"{BASE_PROMPT}/save", json={"mode": "append", "text": "本群直呼昵称"})
        response = await client.post(f"{BASE_PROMPT}/content", json={})

    assert response.status_code == 200, response.text
    assert response.json()["data"]["text"] == "本群直呼昵称"


@pytest.mark.asyncio
async def test_base_prompt_save_rejects_unknown_mode(monkeypatch, tmp_path) -> None:
    client, _ = await _client(monkeypatch, tmp_path)
    async with client:
        response = await client.post(f"{BASE_PROMPT}/save", json={"mode": "prepend", "text": "x"})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_base_prompt_restore_history_version(monkeypatch, tmp_path) -> None:
    client, _ = await _client(monkeypatch, tmp_path)
    async with client:
        first = await client.post(f"{BASE_PROMPT}/save", json={"mode": "append", "text": "第一版"})
        version_id = first.json()["data"]["versions"][0]["id"]
        await client.post(f"{BASE_PROMPT}/save", json={"mode": "replace", "text": "第二版"})
        restored = await client.post(f"{BASE_PROMPT}/restore", json={"version_id": version_id})

    assert restored.status_code == 200, restored.text
    assert restored.json()["data"]["mode"] == "append"
    assert restored.json()["data"]["text"] == "第一版"


@pytest.mark.asyncio
async def test_base_prompt_restore_unknown_version_404(monkeypatch, tmp_path) -> None:
    client, _ = await _client(monkeypatch, tmp_path)
    async with client:
        response = await client.post(f"{BASE_PROMPT}/restore", json={"version_id": "missing"})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_base_prompt_enabled_toggle(monkeypatch, tmp_path) -> None:
    client, _ = await _client(monkeypatch, tmp_path)
    async with client:
        await client.post(f"{BASE_PROMPT}/save", json={"mode": "append", "text": "规则"})
        disabled = await client.post(f"{BASE_PROMPT}/enabled", json={"enabled": False})

    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["data"]["enabled"] is False


@pytest.mark.asyncio
async def test_base_prompt_clear_disables_and_empties_preview(monkeypatch, tmp_path) -> None:
    client, _ = await _client(monkeypatch, tmp_path)
    async with client:
        await client.post(f"{BASE_PROMPT}/save", json={"mode": "replace", "text": "完整基线"})
        cleared = await client.post(f"{BASE_PROMPT}/clear", json={})
        status = await client.get(BASE_PROMPT)

    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["data"] == {"cleared": True}
    data = status.json()["data"]
    assert data["enabled"] is False
    assert data["text_preview"] == ""
    assert data["versions"] == []


@pytest.mark.asyncio
async def test_base_prompt_write_ops_require_write_token(monkeypatch, tmp_path) -> None:
    def _deny(*args, **kwargs):
        raise HTTPException(status_code=401, detail="denied")

    client, _ = await _client(monkeypatch, tmp_path, check_write_token=_deny)
    async with client:
        saved = await client.post(f"{BASE_PROMPT}/save", json={"mode": "append", "text": "x"})
        content = await client.post(f"{BASE_PROMPT}/content", json={})
        cleared = await client.post(f"{BASE_PROMPT}/clear", json={})

    assert saved.status_code == 401
    assert content.status_code == 401
    assert cleared.status_code == 401
