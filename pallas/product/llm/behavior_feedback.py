"""行为反馈自动结算：定期对观察窗口已过的行为 run 推断效果并落盘。

行为 run 在投递时写入 runs.jsonl，效果（engaged/neutral/ignored/awkward/derailed）
此前只在 WebUI 查看会话详情时惰性结算；本模块提供后台 loop 定期结算，
让行为 pattern 的 success_score 学习不依赖人工查看。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from nonebot import get_driver, logger

from pallas.core.foundation.logging import log_rate_limited
from pallas.product.llm.behavior import infer_behavior_feedback
from pallas.product.llm.behavior_store import list_behavior_runs, settle_behavior_run_outcome
from pallas.product.llm.session_store import (
    is_llm_session_store_available,
    list_group_ambient_messages,
    list_user_llm_messages,
)

_SETTLE_INTERVAL_SEC = 300
_SETTLE_WINDOW_SEC = 90
_SETTLE_RUN_LIMIT = 10_000
# 每轮最多结算条数：backlog 分多轮消化，避免一次性大批量结算
# 阻塞事件循环、并让 IGNORED 分数骤降。
_SETTLE_MAX_PER_PASS = 300

_startup_bound = False
_settle_task: asyncio.Task[Any] | None = None


async def settle_pending_behavior_runs(*, now: int | None = None) -> int:
    """结算观察窗口已过的未结算行为 run；返回本次结算数量。"""
    if not is_llm_session_store_available():
        return 0
    now = int(now or time.time())
    runs = list_behavior_runs(limit=_SETTLE_RUN_LIMIT)
    settled = 0
    for run in runs:
        if settled >= _SETTLE_MAX_PER_PASS:
            break
        if run.final_outcome is not None or int(run.created_at) <= 0:
            continue
        if now - int(run.created_at) < _SETTLE_WINDOW_SEC:
            continue
        bot_id = int(run.bot_id or 0)
        user_id = int(run.user_id or 0)
        if bot_id <= 0 or user_id <= 0:
            continue
        try:
            turns = await list_user_llm_messages(bot_id, run.group_id, user_id, limit=50)
            ambient = await list_group_ambient_messages(bot_id, run.group_id, limit=50)
        except Exception as exc:
            log_rate_limited(logger, "warning", "behavior_feedback.query", "行为反馈查询失败：{}", exc)
            continue
        outcome, payload = infer_behavior_feedback(run=run, turns=turns, ambient_turns=ambient, now=now)
        if outcome is None:
            continue
        updated = await asyncio.to_thread(
            settle_behavior_run_outcome,
            run.request_id,
            final_outcome=outcome,
            auto_feedback_payload=payload,
        )
        if updated is not None:
            settled += 1
    return settled


async def _settle_loop() -> None:
    while True:
        await asyncio.sleep(_SETTLE_INTERVAL_SEC)
        try:
            await settle_pending_behavior_runs()
        except Exception as exc:
            log_rate_limited(logger, "warning", "behavior_feedback.loop", "行为反馈自动结算失败：{}", exc)


def register_behavior_feedback_loop() -> None:
    global _startup_bound, _settle_task
    if _startup_bound:
        return
    _startup_bound = True
    driver = get_driver()

    @driver.on_startup
    async def _on_startup() -> None:
        global _settle_task
        _settle_task = asyncio.create_task(_settle_loop(), name="behavior_feedback_settle")

    @driver.on_shutdown
    async def _on_shutdown() -> None:
        global _settle_task
        if _settle_task is not None:
            _settle_task.cancel()
            await asyncio.gather(_settle_task, return_exceptions=True)
            _settle_task = None
