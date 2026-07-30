from __future__ import annotations

import types

import pytest


@pytest.mark.asyncio
async def test_drunk_chat_uses_unified_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.llm_chat import drunk_chat as chat_mod

    added: list[tuple[str, dict]] = []
    removed: list[str] = []
    captured: dict[str, object] = {}

    class DummyGroupConfig:
        def __init__(self, group_id: int, cooldown: int = 10) -> None:
            self.group_id = group_id
            self.cooldown = cooldown

        async def is_cooldown(self, _key: str) -> bool:
            return True

        async def refresh_cooldown(self, _key: str) -> None:
            return None

    async def fake_add_task(task_id: str, payload: dict) -> None:
        added.append((task_id, dict(payload)))

    async def fake_remove_task(task_id: str) -> None:
        removed.append(task_id)

    async def fake_submit_chat_task(request, *, cfg=None):
        captured["request_id"] = request.request_id
        captured["session_id"] = request.session_id
        captured["user_text"] = request.user_text
        captured["system_prompt"] = request.system_prompt
        captured["bot_id"] = request.bot_id
        captured["group_id"] = request.group_id
        captured["mode"] = request.mode
        captured["task"] = request.task
        captured["token_count"] = request.token_count
        return types.SimpleNamespace(ok=True, task_id="unified-task-id", status="processing")

    async def fake_build_prompt(bot_id, group_id, text, *, user_id=None):
        return types.SimpleNamespace(system_prompt="你是牛牛。", token_count=50, temperature=None)

    monkeypatch.setattr(chat_mod, "GroupConfig", DummyGroupConfig)
    monkeypatch.setattr(chat_mod.TaskManager, "add_task", fake_add_task)
    monkeypatch.setattr(chat_mod.TaskManager, "remove_task", fake_remove_task)
    monkeypatch.setattr(chat_mod, "submit_chat_task", fake_submit_chat_task)
    monkeypatch.setattr(chat_mod, "build_drunk_chat_system_prompt", fake_build_prompt)
    monkeypatch.setattr(chat_mod, "is_llm_chat_service_enabled", lambda: True)
    monkeypatch.setattr(chat_mod, "is_legacy_rwkv_drunk_chat_enabled", lambda: False)
    monkeypatch.setattr(chat_mod, "is_chat_tts_enabled", lambda: False)
    monkeypatch.setattr(chat_mod, "ULID", lambda: "chat-request-id")

    class DummyBot:
        self_id = "123456"

    class DummyEvent:
        self_id = "123456"
        group_id = 42
        user_id = 7

        def is_tome(self) -> bool:
            return False

        def get_plaintext(self) -> str:
            return "牛牛 你好呀\n第二行忽略"

    await chat_mod.handle_drunk_chat(DummyBot(), DummyEvent())

    assert removed == []
    assert [task_id for task_id, _ in added] == ["chat-request-id"]
    assert added[0][1]["task_type"] == "chat"
    assert added[0][1]["want_tts"] is False
    assert captured["request_id"] == "chat-request-id"
    assert captured["session_id"] == "123456_42"
    assert captured["user_text"] == "你好呀"
    assert captured["system_prompt"] == "你是牛牛。"
    assert captured["bot_id"] == 123456
    assert captured["group_id"] == 42
    assert captured["mode"] == "drunk"
    assert captured["task"] == "drunk"
    assert captured["token_count"] == 50


@pytest.mark.asyncio
async def test_drunk_chat_yields_to_extension_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.llm_chat import drunk_chat as chat_mod

    monkeypatch.setattr(chat_mod, "extension_drunk_chat_loaded", lambda: True)
    monkeypatch.setattr(chat_mod, "is_llm_chat_service_enabled", lambda: True)

    class DummyEvent:
        self_id = "1"
        group_id = 2

        def is_tome(self) -> bool:
            return True

        def get_plaintext(self) -> str:
            return "你好"

    assert await chat_mod.is_to_drunk_chat(DummyEvent()) is False
