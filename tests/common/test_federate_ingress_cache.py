from __future__ import annotations

import asyncio
from threading import Event
from unittest.mock import AsyncMock

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

from pallas.core.platform.federate import ingress as fed_ingress
from pallas.core.platform.federate import ingress_audit

pytestmark = pytest.mark.usefixtures("isolated_gate_pool")


def test_redis_claim_timeout_defaults_to_three_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fed_ingress, "repo_env_raw_value", lambda _name: None)
    assert fed_ingress.redis_claim_timeout_sec() == 3.0


@pytest.fixture(autouse=True)
def no_federate_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    ingress_audit.reset_federate_ingress_audit_for_tests()
    monkeypatch.setattr(fed_ingress, "_CANDIDATE_WAIT_SEC", 0.0)
    monkeypatch.setattr(fed_ingress, "record_federate_ingress_audit", lambda **_kwargs: None)
    monkeypatch.setattr(
        "pallas.core.platform.federate.candidates.read_federate_ingress_candidate_bot_ids_sync",
        lambda **_kwargs: frozenset(),
    )


@pytest.mark.asyncio
async def test_federate_ingress_win_cache_skips_second_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    fed_ingress.reset_federate_ingress_win_cache_for_tests()
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_bypass_unified", lambda: False)
    monkeypatch.setattr(fed_ingress.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_active", lambda: True)
    monkeypatch.setattr(
        "pallas.core.platform.federate.ingress.load_or_create_deployment_id",
        lambda: "deploy-test",
    )
    claim = AsyncMock(return_value=True)
    monkeypatch.setattr(fed_ingress, "try_claim_cross_federate_message", claim)

    event = GroupMessageEvent.model_construct(
        time=100,
        self_id=111,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=999,
        group_id=12345,
        message_id=1,
        message=Message("hi"),
        raw_message="hi",
    )

    assert await fed_ingress.claim_federate_group_message_ingress(event) is True
    assert await fed_ingress.claim_federate_group_message_ingress(event) is True
    assert claim.await_count == 1


@pytest.mark.asyncio
async def test_federate_ingress_coalesces_concurrent_same_message(monkeypatch: pytest.MonkeyPatch) -> None:
    fed_ingress.reset_federate_ingress_win_cache_for_tests()
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_bypass_unified", lambda: False)
    monkeypatch.setattr(fed_ingress.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_active", lambda: True)
    monkeypatch.setattr(
        "pallas.core.platform.federate.ingress.load_or_create_deployment_id",
        lambda: "deploy-test",
    )

    async def slow_claim(*args, **kwargs) -> bool:
        await asyncio.sleep(0.05)
        return True

    claim = AsyncMock(side_effect=slow_claim)
    monkeypatch.setattr(fed_ingress, "try_claim_cross_federate_message", claim)

    event = GroupMessageEvent.model_construct(
        time=100,
        self_id=111,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=999,
        group_id=12345,
        message_id=1,
        message=Message("hi"),
        raw_message="hi",
    )

    won_a, won_b = await asyncio.gather(
        fed_ingress.claim_federate_group_message_ingress(event),
        fed_ingress.claim_federate_group_message_ingress(event),
    )

    assert won_a is True
    assert won_b is True
    assert claim.await_count == 1


@pytest.mark.asyncio
async def test_federate_ingress_cancelled_owner_releases_inflight_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    fed_ingress.reset_federate_ingress_win_cache_for_tests()
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_bypass_unified", lambda: False)
    monkeypatch.setattr(fed_ingress.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.load_or_create_deployment_id", lambda: "deploy-test")
    started = asyncio.Event()
    calls = 0

    async def blocked_claim(*_args, **_kwargs) -> bool:
        nonlocal calls
        calls += 1
        started.set()
        if calls > 1:
            return True
        await asyncio.Event().wait()
        return True

    monkeypatch.setattr(fed_ingress, "try_claim_cross_federate_message", blocked_claim)
    event = GroupMessageEvent.model_construct(
        time=100,
        self_id=111,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=999,
        group_id=12345,
        message_id=1,
        message=Message("hi"),
        raw_message="hi",
    )

    owner = asyncio.create_task(fed_ingress.claim_federate_group_message_ingress(event))
    await started.wait()
    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner

    assert fed_ingress._inflight_claims == {}
    assert await fed_ingress.claim_federate_group_message_ingress(event) is True
    assert calls == 2
    assert fed_ingress._inflight_claims == {}


@pytest.mark.asyncio
async def test_federate_ingress_old_owner_does_not_cache_replacement_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fed_ingress.reset_federate_ingress_win_cache_for_tests()
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_bypass_unified", lambda: False)
    monkeypatch.setattr(fed_ingress.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.load_or_create_deployment_id", lambda: "deploy-test")
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked_claim(*_args, **_kwargs) -> bool:
        started.set()
        await release.wait()
        return True

    monkeypatch.setattr(fed_ingress, "try_claim_cross_federate_message", blocked_claim)
    event = GroupMessageEvent.model_construct(
        time=100,
        self_id=111,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=999,
        group_id=12345,
        message_id=1,
        message=Message("hi"),
        raw_message="hi",
    )

    owner = asyncio.create_task(fed_ingress.claim_federate_group_message_ingress(event))
    await started.wait()
    cache_key = next(iter(fed_ingress._inflight_claims))
    replacement = asyncio.get_running_loop().create_future()
    fed_ingress._inflight_claims[cache_key] = replacement

    release.set()
    assert await owner is True
    assert fed_ingress._inflight_claims[cache_key] is replacement
    assert not replacement.done()
    assert cache_key not in fed_ingress._win_cache


@pytest.mark.asyncio
async def test_federate_ingress_follower_joins_owner_with_same_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    fed_ingress.reset_federate_ingress_win_cache_for_tests()
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_bypass_unified", lambda: False)
    monkeypatch.setattr(fed_ingress.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.load_or_create_deployment_id", lambda: "deploy-test")
    monkeypatch.setattr(fed_ingress, "redis_claim_timeout_sec", lambda: 0.5)
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked_claim(*_args, **_kwargs) -> bool:
        started.set()
        await release.wait()
        return True

    monkeypatch.setattr(fed_ingress, "try_claim_cross_federate_message", blocked_claim)
    event = GroupMessageEvent.model_construct(
        time=100,
        self_id=111,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=999,
        group_id=12345,
        message_id=1,
        message=Message("hi"),
        raw_message="hi",
    )

    owner = asyncio.create_task(fed_ingress.claim_federate_group_message_ingress(event))
    await started.wait()

    follower = asyncio.create_task(fed_ingress.claim_federate_group_message_ingress(event))
    assert len(fed_ingress._inflight_claims) == 1

    await asyncio.sleep(0.01)
    release.set()
    assert await owner is True
    assert await follower is True
    assert fed_ingress._inflight_claims == {}


@pytest.mark.asyncio
async def test_federate_ingress_follower_cancellation_does_not_cancel_shared_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fed_ingress.reset_federate_ingress_win_cache_for_tests()
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_bypass_unified", lambda: False)
    monkeypatch.setattr(fed_ingress.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.load_or_create_deployment_id", lambda: "deploy-test")
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked_claim(*_args, **_kwargs) -> bool:
        started.set()
        await release.wait()
        return True

    monkeypatch.setattr(fed_ingress, "try_claim_cross_federate_message", blocked_claim)
    event = GroupMessageEvent.model_construct(
        time=100,
        self_id=111,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=999,
        group_id=12345,
        message_id=1,
        message=Message("hi"),
        raw_message="hi",
    )

    owner = asyncio.create_task(fed_ingress.claim_federate_group_message_ingress(event))
    await started.wait()
    cancelled_follower = asyncio.create_task(fed_ingress.claim_federate_group_message_ingress(event))
    survivor = asyncio.create_task(fed_ingress.claim_federate_group_message_ingress(event))
    await asyncio.sleep(0)
    cancelled_follower.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled_follower
    assert len(fed_ingress._inflight_claims) == 1

    release.set()
    assert await owner is True
    assert await survivor is True
    assert fed_ingress._inflight_claims == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["running_timeout", ConnectionError])
async def test_federate_ingress_failed_claim_releases_for_recovery(
    monkeypatch: pytest.MonkeyPatch, failure: type[Exception] | str
) -> None:
    from pallas.core.platform.ingress.fast_path import GateExecutionTimeout

    fed_ingress.reset_federate_ingress_win_cache_for_tests()
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_bypass_unified", lambda: False)
    monkeypatch.setattr(fed_ingress.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.load_or_create_deployment_id", lambda: "deploy-test")
    if failure is TimeoutError:
        monkeypatch.setattr(fed_ingress, "redis_claim_timeout_sec", lambda: 0.01)

    calls = 0

    async def failing_once(*_args, **_kwargs) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            if failure == "running_timeout":
                return GateExecutionTimeout.RUNNING
            raise ConnectionError("redis unavailable")
        return True

    monkeypatch.setattr(fed_ingress, "try_claim_cross_federate_message", failing_once)
    event = GroupMessageEvent.model_construct(
        time=100,
        self_id=111,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=999,
        group_id=12345,
        message_id=1,
        message=Message("hi"),
        raw_message="hi",
    )

    if failure is ConnectionError:
        with pytest.raises(ConnectionError):
            await fed_ingress.claim_federate_group_message_ingress(event)
        assert fed_ingress._inflight_claims == {}
        assert await fed_ingress.claim_federate_group_message_ingress(event) is True
        assert calls == 2
    else:
        # 已开始但超过运行时限的 Redis 操作保守拒绝，不套用错误 fail-open 策略。
        assert await fed_ingress.claim_federate_group_message_ingress(event) is False
        assert fed_ingress._inflight_claims == {}
        assert await fed_ingress.claim_federate_group_message_ingress(event) is False
        assert calls == 1
        # 换一条消息（签名不同）仍可正常抢占。
        other = GroupMessageEvent.model_construct(
            time=101,
            self_id=111,
            post_type="message",
            message_type="group",
            sub_type="normal",
            user_id=999,
            group_id=12345,
            message_id=2,
            message=Message("hi"),
            raw_message="hi",
        )
        assert await fed_ingress.claim_federate_group_message_ingress(other) is True
        assert calls == 2


@pytest.mark.asyncio
async def test_federate_ingress_running_timeout_stays_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.ingress.fast_path import GateExecutionTimeout

    fed_ingress.reset_federate_ingress_win_cache_for_tests()
    monkeypatch.setenv("PALLAS_FEDERATE_CLAIM_FAIL_OPEN", "0")
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_bypass_unified", lambda: False)
    monkeypatch.setattr(fed_ingress.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.load_or_create_deployment_id", lambda: "deploy-test")
    monkeypatch.setattr(fed_ingress, "redis_claim_timeout_sec", lambda: 0.05)

    monkeypatch.setattr(
        fed_ingress,
        "try_claim_cross_federate_message",
        AsyncMock(return_value=GateExecutionTimeout.RUNNING),
    )
    event = GroupMessageEvent.model_construct(
        time=100,
        self_id=111,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=999,
        group_id=12345,
        message_id=1,
        message=Message("hi"),
        raw_message="hi",
    )

    assert await fed_ingress.claim_federate_group_message_ingress(event) is False
    assert fed_ingress._inflight_claims == {}


@pytest.mark.asyncio
async def test_federate_ingress_command_timeout_stays_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.ingress.fast_path import GateExecutionTimeout

    fed_ingress.reset_federate_ingress_win_cache_for_tests()
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_bypass_unified", lambda: False)
    monkeypatch.setattr(fed_ingress.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.load_or_create_deployment_id", lambda: "deploy-test")
    monkeypatch.setattr(fed_ingress, "redis_claim_timeout_sec", lambda: 0.01)

    monkeypatch.setattr(
        fed_ingress,
        "try_claim_cross_federate_message",
        AsyncMock(return_value=GateExecutionTimeout.RUNNING),
    )
    event = GroupMessageEvent.model_construct(
        time=100,
        self_id=111,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=999,
        group_id=12345,
        message_id=1,
        message=Message("/签到"),
        raw_message="/签到",
    )

    # 命令有副作用：超时时默认不放行，避免多个部署各执行一次。
    assert await fed_ingress.claim_federate_group_message_ingress(event, command_traffic=True) is False


@pytest.mark.asyncio
async def test_claim_admission_rejection_does_not_use_chat_fail_open(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.platform.ingress.fast_path import GateNotStarted

    fed_ingress.reset_federate_ingress_win_cache_for_tests()
    monkeypatch.setattr(fed_ingress, "federate_ingress_bypass_unified", lambda: False)
    monkeypatch.setattr(fed_ingress.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr(fed_ingress, "federate_ingress_active", lambda: True)
    monkeypatch.setattr(fed_ingress, "load_or_create_deployment_id", lambda: "dep-local")
    monkeypatch.setattr(fed_ingress, "federate_claim_fail_open", lambda **_kwargs: True)
    monkeypatch.setattr(
        fed_ingress,
        "try_claim_cross_federate_message",
        AsyncMock(return_value=GateNotStarted.SATURATED),
    )
    event = GroupMessageEvent.model_construct(
        time=100,
        self_id=111,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=999,
        group_id=12345,
        message_id=1,
        message=Message("chat fallback"),
        raw_message="chat fallback",
    )

    assert await fed_ingress.claim_federate_group_message_ingress(event, command_traffic=False) is False


@pytest.mark.asyncio
async def test_running_claim_timeout_rejects_without_cancelling_late_redis_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.core.platform.federate import dedup, redis_claim

    fed_ingress.reset_federate_ingress_win_cache_for_tests()
    monkeypatch.setattr(fed_ingress, "federate_ingress_bypass_unified", lambda: False)
    monkeypatch.setattr(fed_ingress.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr(fed_ingress, "federate_ingress_active", lambda: True)
    monkeypatch.setattr(fed_ingress, "load_or_create_deployment_id", lambda: "dep-local")
    monkeypatch.setattr(fed_ingress, "redis_claim_timeout_sec", lambda: 0.05)
    monkeypatch.setattr("pallas.core.platform.federate.config.federate_ingress_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.federate.peer_bots.get_federate_peer_bot_ids", lambda: {1})
    monkeypatch.setattr(redis_claim, "federate_redis_prefix", lambda: "pallas:fed:test")
    monkeypatch.setattr(redis_claim, "federate_claim_ttl_sec", lambda: 60)

    class BlockingClaimRedis:
        def __init__(self) -> None:
            self.started = Event()
            self.release = Event()
            self.finished = Event()
            self.values: dict[str, str] = {}

        def set(self, key: str, value: str, *, nx: bool, ex: int) -> bool:
            self.started.set()
            if not self.release.wait(2):
                raise TimeoutError("test Redis claim was not released")
            if nx and key in self.values:
                self.finished.set()
                return False
            self.values[key] = value
            self.finished.set()
            return True

        def get(self, key: str) -> str | None:
            return self.values.get(key)

    redis = BlockingClaimRedis()
    monkeypatch.setattr(redis_claim, "get_federate_redis_client", lambda: redis)

    async def claim(*args, **kwargs):
        return await dedup.try_claim_cross_federate_message(*args, **kwargs)

    monkeypatch.setattr(fed_ingress, "try_claim_cross_federate_message", claim)
    event = GroupMessageEvent.model_construct(
        time=100,
        self_id=111,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=999,
        group_id=12345,
        message_id=1,
        message=Message("hi"),
        raw_message="hi",
    )

    try:
        assert await fed_ingress.claim_federate_group_message_ingress(event) is False
        assert await asyncio.wait_for(asyncio.to_thread(redis.started.wait, 1), timeout=2)
        redis.release.set()
        assert await asyncio.wait_for(asyncio.to_thread(redis.finished.wait, 1), timeout=2)
    finally:
        redis.release.set()
        dedup._cross_federate_claim_owners.clear()
    assert list(redis.values.values()) == ["dep-local"]


@pytest.mark.asyncio
async def test_unstarted_real_claim_does_not_use_chat_fail_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from queue import Queue
    from threading import Lock

    from pallas.core.platform.federate import dedup, redis_claim
    from pallas.core.platform.ingress import fast_path
    from pallas.core.platform.ingress.fast_path import run_gate_blocking

    fed_ingress.reset_federate_ingress_win_cache_for_tests()
    dedup._cross_federate_claim_owners.clear()
    monkeypatch.setattr(fed_ingress, "federate_ingress_bypass_unified", lambda: False)
    monkeypatch.setattr(fed_ingress.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr(fed_ingress, "federate_ingress_active", lambda: True)
    monkeypatch.setattr(fed_ingress, "load_or_create_deployment_id", lambda: "dep-local")
    monkeypatch.setattr(fed_ingress, "redis_claim_timeout_sec", lambda: 0.05)
    monkeypatch.setattr(fed_ingress, "federate_claim_fail_open", lambda **_kwargs: True)
    monkeypatch.setattr("pallas.core.platform.federate.config.federate_ingress_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.federate.peer_bots.get_federate_peer_bot_ids", lambda: {1})
    monkeypatch.setattr(redis_claim, "federate_redis_prefix", lambda: "pallas:fed:test")
    monkeypatch.setattr(redis_claim, "federate_claim_ttl_sec", lambda: 60)

    rpc_calls = 0

    class ClaimRedis:
        def set(self, *_args, **_kwargs) -> bool:
            nonlocal rpc_calls
            rpc_calls += 1
            return True

        def get(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(redis_claim, "get_federate_redis_client", lambda: ClaimRedis())
    started: Queue[int] = Queue()
    release = Event()
    started_lock = Lock()
    all_workers_started = Event()
    started_count = 0

    def occupy_gate(index: int) -> int:
        nonlocal started_count
        started.put(index)
        with started_lock:
            started_count += 1
            if started_count == fast_path._GATE_WORKERS:
                all_workers_started.set()
        if not release.wait(3):
            raise TimeoutError("test gate worker was not released")
        return index

    blockers = [asyncio.create_task(run_gate_blocking(occupy_gate, i)) for i in range(18)]
    try:
        assert await asyncio.wait_for(asyncio.to_thread(all_workers_started.wait, 1), timeout=2)
        async with asyncio.timeout(1):
            expected_submitted = fast_path._GATE_WORKERS + fast_path._GATE_QUEUE_CAPACITY
            while len(fast_path._submitted_work) != expected_submitted:  # noqa: ASYNC110
                await asyncio.sleep(0.001)

        event = GroupMessageEvent.model_construct(
            time=101,
            self_id=111,
            post_type="message",
            message_type="group",
            sub_type="normal",
            user_id=999,
            group_id=12346,
            message_id=2,
            message=Message("not started"),
            raw_message="not started",
        )

        assert await fed_ingress.claim_federate_group_message_ingress(event, command_traffic=False) is False
        assert rpc_calls == 0
    finally:
        release.set()
        await asyncio.wait_for(
            asyncio.gather(*blockers, return_exceptions=True),
            timeout=4,
        )
        dedup._cross_federate_claim_owners.clear()


@pytest.mark.asyncio
async def test_federate_ingress_redis_error_applies_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_bypass_unified", lambda: False)
    monkeypatch.setattr(fed_ingress.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.load_or_create_deployment_id", lambda: "deploy-test")
    monkeypatch.setattr(fed_ingress, "try_claim_cross_federate_message", AsyncMock(return_value=None))

    event = GroupMessageEvent.model_construct(
        time=100,
        self_id=111,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=999,
        group_id=12345,
        message_id=1,
        message=Message("hi"),
        raw_message="hi",
    )

    fed_ingress.reset_federate_ingress_win_cache_for_tests()
    assert await fed_ingress.claim_federate_group_message_ingress(event) is True

    fed_ingress.reset_federate_ingress_win_cache_for_tests()
    command = GroupMessageEvent.model_construct(
        time=100,
        self_id=111,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=999,
        group_id=12345,
        message_id=2,
        message=Message("/签到"),
        raw_message="/签到",
    )
    assert await fed_ingress.claim_federate_group_message_ingress(command, command_traffic=True) is False


@pytest.mark.asyncio
async def test_federate_ingress_bypass_unified_skips_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    fed_ingress.reset_federate_ingress_win_cache_for_tests()
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_bypass_unified", lambda: True)
    monkeypatch.setattr(fed_ingress.shard_ctx, "sharding_active", lambda: False)
    claim = AsyncMock(return_value=True)
    monkeypatch.setattr(fed_ingress, "try_claim_cross_federate_message", claim)

    event = GroupMessageEvent.model_construct(
        time=100,
        self_id=111,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=999,
        group_id=12345,
        message_id=1,
        message=Message("hi"),
        raw_message="hi",
    )

    assert fed_ingress.federate_ingress_cached_win(event) is True
    assert await fed_ingress.claim_federate_group_message_ingress(event) is True
    claim.assert_not_awaited()


def test_federate_ingress_cached_win_reuses_precomputed_body(monkeypatch: pytest.MonkeyPatch) -> None:
    fed_ingress.reset_federate_ingress_win_cache_for_tests()
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_bypass_unified", lambda: False)
    monkeypatch.setattr(fed_ingress.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_active", lambda: True)
    monkeypatch.setattr(
        "pallas.core.platform.federate.ingress.load_or_create_deployment_id",
        lambda: "deploy-test",
    )
    monkeypatch.setattr(
        "pallas.core.platform.federate.ingress.cross_bot_message_signature", lambda *_args, **_kwargs: "sig"
    )

    cache_key = (
        fed_ingress.FEDERATE_INGRESS_CLAIM_PLUGIN,
        "sig",
        "deploy-test",
    )
    fed_ingress._win_cache[cache_key] = float("inf")

    class _Event:
        group_id = 12345
        user_id = 999
        time = 100
        raw_message = "raw"

        def get_plaintext(self) -> str:
            raise AssertionError("should reuse provided plain/body")

    assert (
        fed_ingress.federate_ingress_cached_win(
            _Event(),
            plain="",
            body="precomputed body",
        )
        is True
    )


@pytest.mark.asyncio
async def test_federate_ingress_claim_reuses_precomputed_body(monkeypatch: pytest.MonkeyPatch) -> None:
    fed_ingress.reset_federate_ingress_win_cache_for_tests()
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_bypass_unified", lambda: False)
    monkeypatch.setattr(fed_ingress.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_active", lambda: True)
    monkeypatch.setattr(
        "pallas.core.platform.federate.ingress.load_or_create_deployment_id",
        lambda: "deploy-test",
    )
    claim = AsyncMock(return_value=True)
    monkeypatch.setattr(fed_ingress, "try_claim_cross_federate_message", claim)

    class _Event:
        group_id = 12345
        user_id = 999
        time = 100
        raw_message = "raw"

        def get_plaintext(self) -> str:
            raise AssertionError("should reuse provided plain/body")

    assert (
        await fed_ingress.claim_federate_group_message_ingress(
            _Event(),
            plain="",
            body="precomputed body",
        )
        is True
    )
    claim.assert_awaited_once()
