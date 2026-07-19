from pallas.core.platform.ai_callback.handlers import failure_reply_for_task
from pallas.core.platform.ai_callback.task_types import CHAT_DRUNK_TASK_TYPE, LLM_CHAT_TASK_TYPE


def test_failure_reply_for_llm_chat_is_silent() -> None:
    reply = failure_reply_for_task({"task_type": LLM_CHAT_TASK_TYPE})
    assert reply is None


def test_failure_reply_for_legacy_ollama_is_silent() -> None:
    reply = failure_reply_for_task({"task_type": "ollama"})
    assert reply is None


def test_failure_reply_for_drunk_chat_is_silent() -> None:
    reply = failure_reply_for_task({"task_type": CHAT_DRUNK_TASK_TYPE})
    assert reply is None
