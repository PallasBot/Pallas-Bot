from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_enqueue_repeater_learn_captures_then_writes_idempotent_work_job(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater import learn_queue

    payload = SimpleNamespace(to_dict=lambda: {"chat": {"group_id": 42}})
    chat = SimpleNamespace(chat_data=SimpleNamespace(group_id=42, bot_id=100))
    event = SimpleNamespace(group_id=42, message_id=99, self_id=100)
    store = SimpleNamespace(enqueue=AsyncMock())
    monkeypatch.setattr(learn_queue, "claim_group_message_event", AsyncMock(return_value=True))
    monkeypatch.setattr("packages.repeater.learner.Learner.capture_for_work", AsyncMock(return_value=payload))
    monkeypatch.setattr(learn_queue, "build_work_job_store", lambda: store)

    assert await learn_queue.enqueue_repeater_learn(chat, event) is True

    job = store.enqueue.await_args.args[0]
    assert job.kind == "repeater.learn"
    assert job.idempotency_key == "repeater.learn:42:99:100"
    assert job.payload == {"chat": {"group_id": 42}}


@pytest.mark.asyncio
async def test_repeater_work_handler_processes_serialized_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater.work_handler import handle_repeater_learn

    process = AsyncMock()
    monkeypatch.setattr("packages.repeater.learner.Learner.process_work_payload", process)

    await handle_repeater_learn({
        "chat": {
            "group_id": 42,
            "user_id": 11,
            "bot_id": 100,
            "raw_message": "这一句",
            "plain_text": "这一句",
            "time": 20,
        },
        "predecessor": None,
    })

    process.assert_awaited_once()
