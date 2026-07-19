from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

from pallas.core.platform.ingress.claim_gate import (
    IngressClaimError,
    ingress_gate_runtime_active,
    shard_worker_ingress_claims,
    unified_ingress_once_claim,
)
from pallas.core.platform.ingress.unified_pass import reset_unified_ingress_once_pass_for_tests
from pallas.core.platform.shard import context as shard_ctx


def test_ingress_gate_runtime_active_false_on_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shard_ctx, "is_hub", lambda: True)
    assert ingress_gate_runtime_active() is False


def test_ingress_gate_runtime_active_true_when_not_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shard_ctx, "is_hub", lambda: False)
    assert ingress_gate_runtime_active() is True


@pytest.mark.asyncio
async def test_unified_ingress_once_claim_skips_when_sharding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shard_ctx, "sharding_active", lambda: True)
    once = AsyncMock(return_value=True)
    monkeypatch.setattr("pallas.core.platform.ingress.claim_gate.try_claim_group_message_once", once)
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
    await unified_ingress_once_claim(event, body="hi", user_id=999)
    once.assert_not_awaited()


@pytest.mark.asyncio
async def test_unified_ingress_once_claim_raises_when_lost(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_unified_ingress_once_pass_for_tests()
    monkeypatch.setattr(shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.claim_gate.try_claim_group_message_once",
        AsyncMock(return_value=False),
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
    with pytest.raises(IngressClaimError) as exc:
        await unified_ingress_once_claim(event, body="hi", user_id=999)
    assert exc.value.outcome == "once_claim_lost"
    assert exc.value.record_claim_lost is True


@pytest.mark.asyncio
async def test_shard_worker_ingress_claims_empty_when_not_sharding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shard_ctx, "sharding_active", lambda: False)
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
    assert await shard_worker_ingress_claims(event, body="hi", user_id=999, self_id=111) == []


@pytest.mark.asyncio
async def test_shard_worker_ingress_claims_returns_marks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shard_ctx, "sharding_active", lambda: True)
    monkeypatch.setattr(shard_ctx, "shard_id", lambda: 2)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.claim_gate.try_claim_cross_shard_message",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "pallas.core.platform.ingress.claim_gate.try_claim_cross_bot_message",
        AsyncMock(return_value=True),
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
    marks = await shard_worker_ingress_claims(event, body="hi", user_id=999, self_id=111)
    assert marks == ["shard_claim", "bot_claim"]


@pytest.mark.asyncio
async def test_shard_worker_ingress_claims_raises_on_shard_loss(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shard_ctx, "sharding_active", lambda: True)
    monkeypatch.setattr(shard_ctx, "shard_id", lambda: 2)
    monkeypatch.setattr(
        "pallas.core.platform.ingress.claim_gate.try_claim_cross_shard_message",
        AsyncMock(return_value=False),
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
    with pytest.raises(IngressClaimError) as exc:
        await shard_worker_ingress_claims(event, body="hi", user_id=999, self_id=111)
    assert exc.value.outcome == "shard_claim_lost"
