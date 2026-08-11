"""AI 异步任务回调 task_type 常量。"""

from __future__ import annotations

LLM_CHAT_TASK_TYPE = "llm_chat"
LEGACY_LLM_CHAT_TASK_TYPES = frozenset({LLM_CHAT_TASK_TYPE, "ollama"})
CHAT_DRUNK_TASK_TYPE = "chat"
DRAW_IMAGE_TASK_TYPE = "draw"
SING_TASK_TYPES = frozenset({"sing", "play", "request"})
TTS_TASK_TYPE = "tts"
VOICE_TASK_TYPES = SING_TASK_TYPES | {CHAT_DRUNK_TASK_TYPE, TTS_TASK_TYPE}

LLM_SESSION_TASK_TYPES = LEGACY_LLM_CHAT_TASK_TYPES

DEFAULT_FAIL_REPLY = "我习惯了站着不动思考。有时候啊，也会被大家突然戳一戳，看看睡着了没有。"
