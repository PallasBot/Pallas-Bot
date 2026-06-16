from __future__ import annotations

import pytest

from src.features.llm.client import delete_llm_chat_session, submit_chat_task
from src.features.llm.config import LlmConfig
from src.features.llm.models import ChatSubmitRequest


@pytest.mark.asyncio
async def test_submit_chat_task_legacy_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def json(self):
            return {"task_id": "task-1", "status": "processing"}

    async def fake_post(url: str, json: dict | None = None, **kwargs):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr("src.features.llm.client.HTTPXClient.post", fake_post)
    monkeypatch.setattr("src.features.llm.client.is_llm_session_store_available", lambda: False)

    cfg = LlmConfig(
        ai_server_host="127.0.0.1",
        ai_server_port=9099,
        legacy_chat_endpoint="/api/ollama/chat",
        use_unified_chat_api=False,
    )
    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id="req-1",
            session_id="sess-1",
            user_text="你好",
            system_prompt="system",
            bot_id=10001,
            group_id=20002,
            user_id=30003,
        ),
        cfg=cfg,
    )
    assert result.ok is True
    assert result.task_id == "task-1"
    assert captured["url"] == "http://127.0.0.1:9099/api/ollama/chat/req-1"
    assert captured["json"]["session"] == "sess-1"
    assert captured["json"]["system_prompt"] == "system"
    assert captured["json"]["text"].startswith("【用户消息")


@pytest.mark.asyncio
async def test_submit_chat_task_unified_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeResponse:
        def json(self):
            return {"task_id": "task-u1", "status": "processing"}

    async def fake_post(url: str, json: dict | None = None, **kwargs):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    monkeypatch.setattr("src.features.llm.client.HTTPXClient.post", fake_post)
    monkeypatch.setattr("src.features.llm.client.is_llm_session_store_available", lambda: False)

    cfg = LlmConfig(use_unified_chat_api=True)
    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id="req-u1",
            session_id="sess-u1",
            user_text="你好",
            system_prompt="system",
            bot_id=10001,
            group_id=20002,
            user_id=30003,
            mode="drunk",
            token_count=50,
        ),
        cfg=cfg,
    )
    assert result.ok is True
    assert captured["url"] == "http://127.0.0.1:9099/api/v1/chat/completions/req-u1"
    payload = captured["json"]
    assert payload["session_id"] == "sess-u1"
    assert payload["system"] == "system"
    assert payload["metadata"]["mode"] == "drunk"
    assert payload["metadata"]["token_count"] == 50
    assert payload["messages"][-1]["content"].startswith("【用户消息")


@pytest.mark.asyncio
async def test_delete_llm_chat_session_unified(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeResponse:
        status_code = 200

    async def fake_delete(url: str, **kwargs):
        captured["url"] = url
        return FakeResponse()

    monkeypatch.setattr("src.features.llm.client.HTTPXClient.delete", fake_delete)

    ok = await delete_llm_chat_session("bot_group", cfg=LlmConfig(use_unified_chat_api=True))
    assert ok is True
    assert captured["url"] == "http://127.0.0.1:9099/api/v1/chat/completions/session/bot_group"


@pytest.mark.asyncio
async def test_submit_chat_task_rejects_when_llm_chat_disabled() -> None:
    cfg = LlmConfig(llm_chat_enabled=False)
    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id="req-off",
            session_id="sess-off",
            user_text="你好",
            system_prompt="system",
        ),
        cfg=cfg,
    )
    assert result.ok is False
    assert result.status == "llm_chat_disabled"


@pytest.mark.asyncio
async def test_submit_chat_task_rejects_empty_user_text() -> None:
    result = await submit_chat_task(
        ChatSubmitRequest(
            request_id="req-2",
            session_id="sess-2",
            user_text="   ",
            system_prompt="system",
        ),
    )
    assert result.ok is False
    assert result.status == "empty_user_message"
