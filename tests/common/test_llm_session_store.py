from __future__ import annotations

import pytest

from src.features.llm.config import LlmConfig, clear_llm_config_cache
from src.features.llm.session_store import (
    append_llm_message,
    clear_llm_messages,
    is_llm_session_store_available,
    list_llm_messages,
    sanitize_stored_content,
)


def test_sanitize_stored_content_strips_control_chars() -> None:
    raw = "hello\x00world"
    assert sanitize_stored_content("user", raw, max_len=200) == "helloworld"


@pytest.mark.asyncio
async def test_llm_session_store_noop_when_disabled(monkeypatch) -> None:
    clear_llm_config_cache()
    monkeypatch.setenv("LLM_SESSION_ENABLED", "0")
    assert is_llm_session_store_available() is False
    ok = await append_llm_message(1, 100, 200, "user", "hi")
    assert ok is False
    assert await list_llm_messages(1, 100) == []


@pytest.mark.asyncio
async def test_llm_session_group_window(pg_engine, monkeypatch) -> None:
    clear_llm_config_cache()
    monkeypatch.setenv("LLM_SESSION_ENABLED", "1")
    monkeypatch.setattr(
        "src.features.llm.session_store.get_llm_config",
        lambda: LlmConfig(
            llm_session_enabled=True,
            llm_session_group_window=3,
            llm_session_user_ttl_sec=0,
        ),
    )
    monkeypatch.setattr("src.features.llm.session_store.is_postgresql_backend", lambda: True)

    for index in range(5):
        ok = await append_llm_message(10001, 20002, 30003, "user", f"msg-{index}")
        assert ok is True

    turns = await list_llm_messages(10001, 20002)
    assert len(turns) == 3
    assert [turn.content for turn in turns] == ["msg-2", "msg-3", "msg-4"]

    removed = await clear_llm_messages(10001, 20002)
    assert removed == 3
    assert await list_llm_messages(10001, 20002) == []
