from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

from pallas.core.platform.federate import ingress as fed_ingress


@pytest.mark.asyncio
async def test_federate_ingress_win_cache_skips_second_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    fed_ingress.reset_federate_ingress_win_cache_for_tests()
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_bypass_unified", lambda: False)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.is_sharding_active", lambda: False)
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
    monkeypatch.setattr("pallas.core.platform.federate.ingress.is_sharding_active", lambda: False)
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
async def test_federate_ingress_bypass_unified_skips_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    fed_ingress.reset_federate_ingress_win_cache_for_tests()
    monkeypatch.setattr("pallas.core.platform.federate.ingress.federate_ingress_bypass_unified", lambda: True)
    monkeypatch.setattr("pallas.core.platform.federate.ingress.is_sharding_active", lambda: False)
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
    monkeypatch.setattr("pallas.core.platform.federate.ingress.is_sharding_active", lambda: False)
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
    monkeypatch.setattr("pallas.core.platform.federate.ingress.is_sharding_active", lambda: False)
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
