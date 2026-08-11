from __future__ import annotations

from pallas.core.platform.ai_callback.handlers import should_append_llm_session
from pallas.core.platform.ai_callback.task_types import LLM_CHAT_TASK_TYPE


def test_should_append_llm_session_only_for_at_chat() -> None:
    assert should_append_llm_session({"task_type": LLM_CHAT_TASK_TYPE}) is True
    assert should_append_llm_session({"task_type": "drunk"}) is False
