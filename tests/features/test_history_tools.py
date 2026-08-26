"""群聊历史工具测试。"""

from __future__ import annotations

import pytest

from pallas.product.llm.tools.context import ToolInvokeContext
from pallas.product.llm.tools.history import handle_chat_history, handle_recent_summary


@pytest.mark.asyncio
async def test_chat_history_uses_expanded_default_window(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, int] = {}

    async def fake_rows(_context: ToolInvokeContext, *, limit: int) -> list[dict[str, str]]:
        captured["limit"] = limit
        return [{"speaker": "甲", "text": "最近讨论工具", "time": "1"}]

    monkeypatch.setattr("pallas.product.llm.tools.history.recent_group_message_rows", fake_rows)

    result = await handle_chat_history({}, ToolInvokeContext(bot_id=1, group_id=2, user_id=3))

    assert captured["limit"] == 48
    assert result["result"]["message_count"] == 1


@pytest.mark.asyncio
async def test_chat_history_caps_expanded_requested_window(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, int] = {}

    async def fake_rows(_context: ToolInvokeContext, *, limit: int) -> list[dict[str, str]]:
        captured["limit"] = limit
        return []

    monkeypatch.setattr("pallas.product.llm.tools.history.recent_group_message_rows", fake_rows)

    await handle_chat_history({"limit": 1000}, ToolInvokeContext(bot_id=1, group_id=2, user_id=3))

    assert captured["limit"] == 64


@pytest.mark.asyncio
async def test_recent_summary_uses_expanded_window(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, int] = {}

    async def fake_rows(_context: ToolInvokeContext, *, limit: int) -> list[dict[str, str]]:
        captured["limit"] = limit
        return [{"speaker": "甲", "text": "工具讨论", "time": "1"}] * 5

    monkeypatch.setattr("pallas.product.llm.tools.history.recent_group_message_rows", fake_rows)

    result = await handle_recent_summary({}, ToolInvokeContext(bot_id=1, group_id=2, user_id=3))

    assert captured["limit"] == 48
    assert result["result"]["message_count"] == 5
