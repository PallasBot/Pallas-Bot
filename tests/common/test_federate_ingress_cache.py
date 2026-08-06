from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

from pallas.core.platform.federate import ingress as fed_ingress


@pytest.fixture(autouse=True)
def no_federate_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fed_ingress, "_CANDIDATE_WAIT_SEC", 0.0)
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

    async def blocked_claim(*_args, **_kwargs) -> bool:
        started.set()
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


@pytest.mark.asyncio
async def test_federate_ingress_follower_timeout_clears_inflight_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    fed_ingress.reset_federate_ingress_win_cache_for_tests()
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_bypass_unified", lambda: False)
    monkeypatch.setattr(fed_ingress.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_active", lambda: True)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.load_or_create_deployment_id", lambda: "deploy-test")
    monkeypatch.setattr(fed_ingress, "_INFLIGHT_CLAIM_WAIT_SEC", 0.01)
    started = asyncio.Event()

    async def blocked_claim(*_args, **_kwargs) -> bool:
        started.set()
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

    assert await fed_ingress.claim_federate_group_message_ingress(event) is False
    assert fed_ingress._inflight_claims == {}

    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner


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
