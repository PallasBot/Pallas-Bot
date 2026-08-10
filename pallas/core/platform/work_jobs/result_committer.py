"""提交 durable work handler 返回的结构化 Bot 动作。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from typing import Any

    from pallas.api.runtime import DirectWorkResult

    type BotActionDispatcher = Callable[[str, int, dict[str, Any]], Awaitable[tuple[bool, Any]]]


class WorkResultCommitError(RuntimeError):
    committed = True


async def dispatch_bot_action(
    action: str,
    target_bot_id: int,
    payload: dict,
    *,
    timeout_sec: float,
) -> tuple[bool, object]:
    from pallas.core.platform.shard.coord.bot_action import invoke_bot_action

    return await invoke_bot_action(action, target_bot_id, payload, timeout_sec=timeout_sec)


class WorkResultCommitter:
    def __init__(self, *, dispatcher=dispatch_bot_action) -> None:
        self._dispatcher = dispatcher

    async def commit(self, result: DirectWorkResult) -> bool:
        if not result.actions:
            return False
        for action in result.actions:
            ok, _response = await self._dispatcher(
                action.action,
                action.target_bot_id,
                action.payload,
                timeout_sec=action.timeout_sec,
            )
            if not ok:
                raise WorkResultCommitError(f"work result action was not accepted: {action.action}")
        return True
