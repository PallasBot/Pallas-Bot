"""AI 异步任务回调：路由执行、投递与 task_type 策略。"""

from pallas.core.platform.ai_callback.delivery import send_group_message, send_group_voice
from pallas.core.platform.ai_callback.task_types import (
    CHAT_DRUNK_TASK_TYPE,
    DEFAULT_FAIL_REPLY,
    LEGACY_LLM_CHAT_TASK_TYPES,
    LLM_CHAT_TASK_TYPE,
    LLM_SESSION_TASK_TYPES,
    SING_TASK_TYPES,
    TTS_TASK_TYPE,
    VOICE_TASK_TYPES,
)

__all__ = [
    "CHAT_DRUNK_TASK_TYPE",
    "DEFAULT_FAIL_REPLY",
    "LEGACY_LLM_CHAT_TASK_TYPES",
    "LLM_CHAT_TASK_TYPE",
    "LLM_SESSION_TASK_TYPES",
    "SING_TASK_TYPES",
    "TTS_TASK_TYPE",
    "VOICE_TASK_TYPES",
    "register_ai_callback_http",  # noqa: F822
    "resolve_callback_task",  # noqa: F822
    "run_ai_callback",  # noqa: F822
    "send_group_message",
    "send_group_voice",
]


def __getattr__(name: str):
    if name == "register_ai_callback_http":
        from pallas.core.platform.ai_callback.http import register_ai_callback_http

        return register_ai_callback_http
    if name in {"resolve_callback_task", "run_ai_callback"}:
        from pallas.core.platform.ai_callback import runner

        return getattr(runner, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
