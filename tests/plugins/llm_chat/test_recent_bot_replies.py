from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_load_recent_bot_plain_replies_filters_and_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.llm_chat.chat_message import load_recent_bot_plain_replies

    rows = [
        SimpleNamespace(user_id=10, bot_id=0, plain_text="user identity"),
        SimpleNamespace(user_id=0, bot_id=10, plain_text="bot identity"),
        SimpleNamespace(user_id=10, bot_id=0, plain_text="[CQ:image,file=x]"),
        SimpleNamespace(user_id=10, bot_id=0, plain_text="   "),
        SimpleNamespace(user_id=99, bot_id=0, plain_text="other"),
    ]
    repo = SimpleNamespace(find_recent_in_group=lambda *_args, **_kwargs: None)

    async def find_recent(*_args, **kwargs):
        assert kwargs["limit"] == 48
        return rows

    repo.find_recent_in_group = find_recent
    monkeypatch.setattr("pallas.core.foundation.db.make_message_repository", lambda: repo)

    assert await load_recent_bot_plain_replies(10, 20, limit=9) == ["user identity", "bot identity"]
    assert await load_recent_bot_plain_replies(10, 20, limit=1) == ["user identity"]
    assert await load_recent_bot_plain_replies(10, 20, limit=0) == ["user identity"]


@pytest.mark.asyncio
async def test_load_recent_bot_plain_replies_repo_failure_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.llm_chat.chat_message import load_recent_bot_plain_replies

    async def fail(*_args, **_kwargs):
        raise RuntimeError("db unavailable")

    repo = SimpleNamespace(find_recent_in_group=fail)
    monkeypatch.setattr("pallas.core.foundation.db.make_message_repository", lambda: repo)

    assert await load_recent_bot_plain_replies(10, 20) == []
