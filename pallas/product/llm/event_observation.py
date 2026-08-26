"""进程内事件模拟的生产观测挂载点。

harness（`tools/llm_event_harness.py`）在事件 dispatch 期间设置 `current_event_observation`，
生产链路过 provider 前调用 `record_provider_prompt_hit` 上报实际进入模型的 system prompt，
从而让 A/B 测试能确认变体 prompt 真的命中了 Provider，而非只记录命令行参数。
未设置观测时这些调用均为空操作，不影响正常生产链。
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

current_event_observation: ContextVar[Any | None] = ContextVar(
    "current_event_observation",
    default=None,
)

_PROMPT_HIT_LIMIT = 20000


def _system_content(messages: Any) -> str:
    if isinstance(messages, (list, tuple)):
        for message in messages:
            if isinstance(message, dict) and str(message.get("role") or "") == "system" and message.get("content"):
                content = str(message.get("content") or "")
                return content
    return ""


def record_event_stage(stage: str, status: str, **extra: Any) -> None:
    observation = current_event_observation.get()
    if observation is None:
        return
    stages = getattr(observation, "stages", None)
    if isinstance(stages, list):
        stages.append({"stage": str(stage), "status": str(status), **extra})


def record_provider_prompt_hit(messages: Any) -> None:
    observation = current_event_observation.get()
    if observation is None:
        return
    system = _system_content(messages)
    prompt_hits = getattr(observation, "prompt_hits", None)
    if isinstance(prompt_hits, list):
        if len(system) > _PROMPT_HIT_LIMIT:
            system = system[:_PROMPT_HIT_LIMIT]
        prompt_hits.append(system)
    stages = getattr(observation, "stages", None)
    if isinstance(stages, list):
        stages.append({"stage": "provider", "status": "prompted", "system_prefix": system[:120]})
