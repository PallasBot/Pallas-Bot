from __future__ import annotations

import asyncio
from threading import Event, Thread, get_ident
from unittest.mock import AsyncMock

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

from pallas.core.platform.ingress import gate
from pallas.core.platform.ingress.group_admin_owner import GroupAdminOwnerIngressDecision


class BlockingRedis:
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.thread_id: int | None = None

    def get(self, _key: str) -> int:
        self.thread_id = get_ident()
        self.started.set()
        self.release.wait()
        return 0


def _event() -> GroupMessageEvent:
    return GroupMessageEvent.model_construct(
        time=100,
        self_id=111,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=999,
        group_id=12345,
        message_id=1,
        message=Message("普通消息"),
        raw_message="普通消息",
    )


def _prepare_gate(monkeypatch: pytest.MonkeyPatch, redis: BlockingRedis, decision: str):
    monkeypatch.setattr(gate, "ingress_gate_active", lambda: True)
    monkeypatch.setattr(gate.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr(gate, "remember_local_group_bot", lambda *_args: None)
    monkeypatch.setattr(gate, "should_record_ingress_metrics", lambda _self_id: False)
    monkeypatch.setattr(gate, "known_bot_sender", lambda **_kwargs: False)
    monkeypatch.setattr(gate, "pallas_at_targets", lambda _event: frozenset())
    monkeypatch.setattr(
        gate,
        "group_admin_owner_ingress_decision",
        AsyncMock(return_value=GroupAdminOwnerIngressDecision(True)),
    )
    monkeypatch.setattr(gate, "ingress_fanout_bypasses_claim", lambda _plain: False)
    monkeypatch.setattr(gate, "touch_federate_present_group", lambda _group_id: None)
    monkeypatch.setattr(gate, "should_yield_federate_ingress_for_peer_command", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(gate, "command_lane_traffic", lambda _plain: False)
    monkeypatch.setattr(gate, "message_at_fleet_bot", lambda _event: False)
    monkeypatch.setattr(
        gate,
        "ingress_once_claim_safe_before_host_gates",
        lambda *_args, **_kwargs: redis.get("ingress") == 0 if decision == "once" else False,
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.alias_route.fleet_bots_matching_plain",
        lambda _plain: (),
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.alias_route.should_yield_ingress_for_peer_alias",
        lambda **_kwargs: False,
    )
    monkeypatch.setattr(
        gate,
        "hosted_activity_claim_is_hosted",
        lambda *_args, **_kwargs: redis.get("hosted_claim") == 1 if decision == "hosted_claim" else False,
    )
    monkeypatch.setattr(
        gate,
        "hosted_activity_ingress_passes",
        lambda *_args, **_kwargs: redis.get("hosted_pass") == 0 if decision == "hosted_pass" else True,
    )
    claim = AsyncMock(return_value=[])
    monkeypatch.setattr(gate, "run_ingress_message_claim", claim)
    monkeypatch.setattr(gate, "dream_session_ingress_passes", AsyncMock(return_value=True))
    monkeypatch.setattr(gate, "claim_federate_group_message_ingress", AsyncMock(return_value=True))
    return claim


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["once", "hosted_claim", "hosted_pass"])
async def test_ingress_redis_decisions_leave_event_loop_responsive(
    monkeypatch: pytest.MonkeyPatch,
    decision: str,
) -> None:
    redis = BlockingRedis()
    _prepare_gate(monkeypatch, redis, decision)
    heartbeat = Event()
    released_after_heartbeat = Event()

    def release_guard() -> None:
        redis.started.wait(5)
        if heartbeat.wait(2):
            released_after_heartbeat.set()
        redis.release.set()

    guard = Thread(target=release_guard, daemon=True)
    guard.start()

    async def pulse() -> None:
        await asyncio.sleep(0)
        heartbeat.set()

    class Bot:
        self_id = "111"

    task = asyncio.create_task(gate.ingress_group_message_gate(Bot(), _event()))
    heartbeat_task = asyncio.create_task(pulse())
    await asyncio.wait_for(asyncio.to_thread(redis.started.wait), timeout=5)
    await heartbeat_task
    await task
    await asyncio.to_thread(guard.join, 5)

    assert released_after_heartbeat.is_set()
    assert redis.thread_id != get_ident()


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["once", "hosted_claim", "hosted_pass"])
async def test_cancelled_ingress_does_not_continue_to_claim(
    monkeypatch: pytest.MonkeyPatch,
    decision: str,
) -> None:
    redis = BlockingRedis()
    claim = _prepare_gate(monkeypatch, redis, decision)
    loop = asyncio.get_running_loop()
    task_done = Event()
    cancelled_before_release = Event()

    async def run_gate() -> None:
        class Bot:
            self_id = "111"

        await gate.ingress_group_message_gate(Bot(), _event())

    task = asyncio.create_task(run_gate())
    task.add_done_callback(lambda _task: task_done.set())

    def cancel_guard() -> None:
        redis.started.wait(5)
        loop.call_soon_threadsafe(task.cancel)
        if task_done.wait(2):
            cancelled_before_release.set()
        redis.release.set()

    guard = Thread(target=cancel_guard, daemon=True)
    guard.start()
    await asyncio.wait_for(asyncio.to_thread(redis.started.wait), timeout=5)
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.to_thread(guard.join, 5)

    assert cancelled_before_release.is_set()
    claim.assert_not_called()
