"""work aux 的复读学习处理器。"""

from __future__ import annotations

from typing import Any

from .learner import Learner
from .work_payload import RepeaterLearnPayload


async def handle_repeater_learn(payload: dict[str, Any]) -> None:
    await Learner.process_work_payload(RepeaterLearnPayload.from_dict(payload))


def repeater_work_handlers():
    return {"repeater.learn": handle_repeater_learn}
