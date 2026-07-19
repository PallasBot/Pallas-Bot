"""AI 异步任务回调 task_type 常量。"""

from __future__ import annotations

LLM_CHAT_TASK_TYPE = "llm_chat"
LEGACY_LLM_CHAT_TASK_TYPES = frozenset({LLM_CHAT_TASK_TYPE, "ollama"})
CHAT_DRUNK_TASK_TYPE = "chat"
REPEATER_POLISH_TASK_TYPE = "repeater_polish"
REPEATER_POLISH_LITE_TASK_TYPE = "repeater_polish_lite"
REPEATER_SELECT_TASK_TYPE = "repeater_select"
REPEATER_FALLBACK_TASK_TYPE = "repeater_fallback"
REPEATER_LLM_TASK_TYPES = frozenset({
    REPEATER_FALLBACK_TASK_TYPE,
    REPEATER_POLISH_TASK_TYPE,
    REPEATER_POLISH_LITE_TASK_TYPE,
    REPEATER_SELECT_TASK_TYPE,
})
DRAW_IMAGE_TASK_TYPE = "draw"
SING_TASK_TYPES = frozenset({"sing", "play", "request"})

LLM_SESSION_TASK_TYPES = LEGACY_LLM_CHAT_TASK_TYPES

DEFAULT_FAIL_REPLY = "我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有。"
