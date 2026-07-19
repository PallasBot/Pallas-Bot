from __future__ import annotations

from pallas.core.shared.ai_capability_request import build_llm_chat_capability_body


def test_build_llm_chat_capability_body() -> None:
    body = build_llm_chat_capability_body(
        request_id="req-1",
        bot_id=10001,
        group_id=20002,
        user_id=30003,
        session_id="sess-1",
        timeout_sec=30.0,
        payload={
            "session_id": "sess-1",
            "system": "system",
            "messages": [{"role": "user", "content": "hi"}],
            "metadata": {"task": "llm_chat"},
        },
    )
    assert body["request_id"] == "req-1"
    assert body["capability"] == "llm.chat"
    assert body["caller"] == {"source": "bot", "bot_id": 10001, "plugin": "llm_chat"}
    assert body["context"]["group_id"] == 20002
    assert body["context"]["user_id"] == 30003
    assert body["context"]["session_id"] == "sess-1"
    assert body["policy"]["timeout_sec"] == 30.0
    assert body["payload"]["metadata"]["task"] == "llm_chat"
