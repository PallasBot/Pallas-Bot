"""ingress_gate 用的 unified / worker claim 薄层。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pallas.core.platform.ingress.unified_pass import mark_unified_ingress_once_won
from pallas.core.platform.multi_bot.dedup import (
    try_claim_cross_bot_message,
    try_claim_cross_shard_message,
    try_claim_group_message_once,
)
from pallas.core.platform.shard import context as shard_ctx

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent

INGRESS_CLAIM_PLUGIN = "ingress_gate"
INGRESS_SHARD_CLAIM_PLUGIN = "ingress_gate_shard"


class IngressClaimError(Exception):
    """ingress claim 未胜出。"""

    def __init__(self, outcome: str, *, message: str, record_claim_lost: bool = False) -> None:
        self.outcome = outcome
        self.record_claim_lost = record_claim_lost
        super().__init__(message)


def ingress_gate_runtime_active() -> bool:
    """hub 不跑群消息 ingress；unified / worker 启用。"""
    return not shard_ctx.is_hub()


async def unified_ingress_once_claim(
    event: GroupMessageEvent,
    *,
    body: str,
    user_id: int,
) -> None:
    """单进程 once claim；胜出后写入 unified_pass。"""
    if shard_ctx.sharding_active():
        return
    if not await try_claim_group_message_once(
        INGRESS_CLAIM_PLUGIN,
        event.group_id,
        user_id,
        body,
        event.time,
        use_plaintext=True,
        include_message_time=True,
    ):
        raise IngressClaimError(
            "once_claim_lost",
            message="ingress unified once claim lost",
            record_claim_lost=True,
        )
    mark_unified_ingress_once_won(event, body=body)


async def run_ingress_message_claim(
    event: GroupMessageEvent,
    *,
    body: str,
    user_id: int,
    self_id: int,
    sharding_active: bool,
    metrics: bool,
) -> list[str]:
    """统一 / 分片 ingress claim 单入口；返回 timer mark 名列表。"""
    if not sharding_active:
        await unified_ingress_once_claim(event, body=body, user_id=user_id)
        return ["once_claim"]
    marks = await shard_worker_ingress_claims(
        event,
        body=body,
        user_id=user_id,
        self_id=self_id,
    )
    if metrics:
        from pallas.core.platform.shard.ingress_metrics import record_ingress_claim

        record_ingress_claim(won=True)
    return marks


async def shard_worker_ingress_claims(
    event: GroupMessageEvent,
    *,
    body: str,
    user_id: int,
    self_id: int,
) -> list[str]:
    """分片 worker：跨片 claim 后按牛 claim；返回成功的 timer mark 名列表。"""
    if not shard_ctx.sharding_active():
        return []
    marks: list[str] = []
    shard_id = shard_ctx.shard_id()
    if not await try_claim_cross_shard_message(
        INGRESS_SHARD_CLAIM_PLUGIN,
        event.group_id,
        user_id,
        body,
        event.time,
        shard_id,
        use_plaintext=True,
        include_message_time=True,
    ):
        raise IngressClaimError(
            "shard_claim_lost",
            message="ingress shard claim lost",
            record_claim_lost=True,
        )
    marks.append("shard_claim")
    if not await try_claim_cross_bot_message(
        INGRESS_CLAIM_PLUGIN,
        event.group_id,
        user_id,
        body,
        event.time,
        self_id,
        use_plaintext=True,
        include_message_time=True,
    ):
        raise IngressClaimError(
            "bot_claim_lost",
            message="ingress bot claim lost",
            record_claim_lost=True,
        )
    marks.append("bot_claim")
    return marks
