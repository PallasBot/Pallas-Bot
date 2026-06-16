from __future__ import annotations

import pytest

from src.features.llm.client import submit_chat_task
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
