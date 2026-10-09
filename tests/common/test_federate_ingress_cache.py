from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

from pallas.core.platform.federate import ingress as fed_ingress
from pallas.core.platform.federate import ingress_audit


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
async def test_federate_ingress_follower_timeout_keeps_owner_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    fed_ingress.reset_federate_ingress_win_cache_for_tests()
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_bypass_unified", lambda: False)
    monkeypatch.setattr(fed_ingress.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.load_or_create_deployment_id", lambda: "deploy-test")
    monkeypatch.setattr(fed_ingress, "_INFLIGHT_CLAIM_WAIT_SEC", 0.01)
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

    assert await fed_ingress.claim_federate_group_message_ingress(event) is False
    assert len(fed_ingress._inflight_claims) == 1

    # A later follower still joins the original owner instead of starting a duplicate claim.
    monkeypatch.setattr(fed_ingress, "_INFLIGHT_CLAIM_WAIT_SEC", 1.0)
    follower = asyncio.create_task(fed_ingress.claim_federate_group_message_ingress(event))
    await asyncio.sleep(0)
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
@pytest.mark.parametrize("failure", [TimeoutError, ConnectionError])
async def test_federate_ingress_failed_claim_releases_for_recovery(
    monkeypatch: pytest.MonkeyPatch, failure: type[Exception]
) -> None:
    fed_ingress.reset_federate_ingress_win_cache_for_tests()
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_bypass_unified", lambda: False)
    monkeypatch.setattr(fed_ingress.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.load_or_create_deployment_id", lambda: "deploy-test")
    if failure is TimeoutError:
        monkeypatch.setattr(fed_ingress, "_REDIS_CLAIM_TIMEOUT_SEC", 0.01)

    calls = 0

    async def failing_once(*_args, **_kwargs) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            if failure is TimeoutError:
                await asyncio.Event().wait()
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
    else:
        assert await fed_ingress.claim_federate_group_message_ingress(event) is False
    assert fed_ingress._inflight_claims == {}
    assert await fed_ingress.claim_federate_group_message_ingress(event) is True
    assert calls == 2


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
