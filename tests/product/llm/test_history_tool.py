from __future__ import annotations

from types import SimpleNamespace

import pytest

from pallas.product.llm.tools.context import ToolInvokeContext
from pallas.product.llm.tools.history import handle_chat_history, handle_recent_summary


@pytest.mark.asyncio
async def test_history_tool_reads_full_group_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    messages = [
        SimpleNamespace(user_id=11, sender_name="阿灿", plain_text="周五八点开黑吗", time=1),
        SimpleNamespace(user_id=22, sender_name="小明", plain_text="我带新图", time=2),
        SimpleNamespace(user_id=99, sender_name="牛牛", plain_text="我也来", time=3),
    ]

    class Repo:
        async def find_recent_in_group(self, group_id: int, *, limit: int):
            assert group_id == 42
            assert limit == 25
            return messages

    monkeypatch.setattr("pallas.core.foundation.db.make_message_repository", lambda: Repo())

    result = await handle_chat_history(
        {},
        ToolInvokeContext(bot_id=99, group_id=42, user_id=11),
    )

    assert result["ok"] is True
    payload = result["result"]
    assert payload["message_count"] == 2
    assert payload["messages"][0]["speaker"] == "阿灿"
    assert all(item["speaker"] != "牛牛" for item in payload["messages"])


@pytest.mark.asyncio
async def test_history_tool_requires_group_context() -> None:
    result = await handle_chat_history({}, ToolInvokeContext(bot_id=1, group_id=None, user_id=2))

    assert result == {"ok": False, "error": "group_context_required"}


@pytest.mark.asyncio
async def test_recent_summary_uses_full_group_messages_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock

    messages = [
        SimpleNamespace(user_id=index % 2 + 11, sender_name=f"群友{index}", plain_text=f"讨论第{index}条", time=index)
        for index in range(8)
    ]

    class Repo:
        async def find_recent_in_group(self, group_id: int, *, limit: int):
            assert group_id == 42
            assert limit == 25
            return messages

    complete = AsyncMock(return_value={"content": "大家在讨论周五开黑的时间和分工。"})
    monkeypatch.setattr("pallas.core.foundation.db.make_message_repository", lambda: Repo())
    monkeypatch.setattr("pallas.product.llm.provider_client.complete_chat_message", complete)
    monkeypatch.setattr("pallas.product.llm.tools.history._recent_summary_cache", {})

    context = ToolInvokeContext(bot_id=99, group_id=42, user_id=11)
    first = await handle_recent_summary({}, context)
    second = await handle_recent_summary({}, context)

    assert first["result"]["summary"] == "大家在讨论周五开黑的时间和分工。"
    assert second["result"]["summary"] == first["result"]["summary"]
    assert complete.await_count == 1


@pytest.mark.asyncio
async def test_recent_summary_returns_short_message_without_model(monkeypatch: pytest.MonkeyPatch) -> None:
    messages = [SimpleNamespace(user_id=11, sender_name="阿灿", plain_text="早", time=1)]

    class Repo:
        async def find_recent_in_group(self, group_id: int, *, limit: int):
            return messages

    monkeypatch.setattr("pallas.core.foundation.db.make_message_repository", lambda: Repo())

    result = await handle_recent_summary({}, ToolInvokeContext(bot_id=99, group_id=42, user_id=11))

    assert result["ok"] is True
    assert result["result"]["summary"] == "最近消息不多，还没有形成明确话题。"
