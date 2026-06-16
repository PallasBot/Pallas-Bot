from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from nonebot.adapters.onebot.v11.exception import NetworkError

from src.platform.ai_callback import runner as ai_callback_runner
from src.platform.ai_callback.task_types import REPEATER_FALLBACK_TASK_TYPE, REPEATER_POLISH_TASK_TYPE


@pytest.mark.asyncio
async def test_run_ai_callback_falls_back_to_shared_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=None)
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "get_task",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        ai_callback_runner,
        "get_ai_task_record",
        lambda _task_id: {"bot_id": "111", "group_id": 222},
    )
    remove_task = AsyncMock()
    monkeypatch.setattr(ai_callback_runner.TaskManager, "remove_task", remove_task)
    monkeypatch.setattr(ai_callback_runner, "remove_ai_task", lambda _task_id: None)

    result = await ai_callback_runner.run_ai_callback("task-1", status="success", text="hello")

    assert result == {"message": "ok"}
    remove_task.assert_awaited_once_with("task-1")


@pytest.mark.asyncio
async def test_run_ai_callback_send_timeout_returns_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = MagicMock()
    bot.call_api = AsyncMock(side_effect=NetworkError("WebSocket call api send_group_msg timeout"))
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "get_task",
        AsyncMock(return_value={"bot_id": "111", "group_id": 222}),
    )
    remove_task = AsyncMock()
    monkeypatch.setattr(ai_callback_runner.TaskManager, "remove_task", remove_task)
    monkeypatch.setattr(ai_callback_runner, "remove_ai_task", lambda _task_id: None)

    result = await ai_callback_runner.run_ai_callback("task-1", status="success", text="hello")

    assert result == {"message": "failed"}
    remove_task.assert_awaited_once_with("task-1")


@pytest.mark.asyncio
async def test_run_ai_callback_get_bot_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_get_bot(_bot_id: str):
        raise ValueError("bot not found")

    monkeypatch.setattr(ai_callback_runner, "get_bot", raise_get_bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "get_task",
        AsyncMock(return_value={"bot_id": "111", "group_id": 222}),
    )

    result = await ai_callback_runner.run_ai_callback("task-1", status="success", text="hello")

    assert result == {"message": "failed"}


@pytest.mark.asyncio
async def test_run_ai_callback_repeater_fallback_failed_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=None)
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "get_task",
        AsyncMock(
            return_value={
                "bot_id": "111",
                "group_id": 222,
                "task_type": REPEATER_FALLBACK_TASK_TYPE,
            }
        ),
    )
    remove_task = AsyncMock()
    monkeypatch.setattr(ai_callback_runner.TaskManager, "remove_task", remove_task)
    monkeypatch.setattr(ai_callback_runner, "remove_ai_task", lambda _task_id: None)

    result = await ai_callback_runner.run_ai_callback("task-1", status="failed")

    assert result == {"message": "ok"}
    bot.call_api.assert_not_awaited()
    remove_task.assert_awaited_once_with("task-1")


@pytest.mark.asyncio
async def test_run_ai_callback_repeater_polish_failed_uses_fallback_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value=None)
    monkeypatch.setattr(ai_callback_runner, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr(
        ai_callback_runner.TaskManager,
        "get_task",
        AsyncMock(
            return_value={
                "bot_id": "111",
                "group_id": 222,
                "task_type": REPEATER_POLISH_TASK_TYPE,
                "fallback_text": "语料原文",
            }
        ),
    )
    remove_task = AsyncMock()
    monkeypatch.setattr(ai_callback_runner.TaskManager, "remove_task", remove_task)
    monkeypatch.setattr(ai_callback_runner, "remove_ai_task", lambda _task_id: None)

    result = await ai_callback_runner.run_ai_callback("task-1", status="failed")

    assert result == {"message": "ok"}
    bot.call_api.assert_awaited_once()
    call_kwargs = bot.call_api.await_args.kwargs
    assert call_kwargs["group_id"] == 222
    assert call_kwargs["message"] == "语料原文"
    remove_task.assert_awaited_once_with("task-1")
