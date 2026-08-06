from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message

from pallas.core.platform.federate import candidates, ingress
from pallas.core.platform.federate import ingress_audit


def test_candidate_registry_writes_capable_bot_without_message_body(monkeypatch) -> None:
    client = MagicMock()
    monkeypatch.setattr(candidates, "get_federate_redis_client", lambda: client)
    monkeypatch.setattr(candidates, "federate_redis_prefix", lambda: "pallas:fed:pool-1")

    assert (
        candidates.register_federate_ingress_candidate_sync(
            group_id=733291779,
            user_id=2976753330,
            body="漂亮牛艾特我一下",
            message_time=1786007349,
            capability="llm_alias",
            bot_id=2357682124,
        )
        is True
    )

    key, member = client.sadd.call_args.args
    assert key.startswith("pallas:fed:pool-1:ingress_candidates:733291779:")
    assert "漂亮牛" not in key
    assert member == "llm_alias:2357682124"
    client.expire.assert_called_once_with(key, candidates.CANDIDATE_TTL_SEC)


def test_candidate_registry_reads_registered_bots(monkeypatch) -> None:
    client = MagicMock()
    client.smembers.return_value = {b"llm_alias:3907360849", b"command:2357682124", b"invalid"}
    monkeypatch.setattr(candidates, "get_federate_redis_client", lambda: client)
    monkeypatch.setattr(candidates, "federate_redis_prefix", lambda: "pallas:fed:pool-1")

    assert candidates.read_federate_ingress_candidate_bot_ids_sync(
        group_id=733291779,
        user_id=2976753330,
        body="漂亮牛艾特我一下",
        message_time=1786007349,
        capability="llm_alias",
    ) == frozenset({2357682124, 3907360849})


def make_event() -> GroupMessageEvent:
    return GroupMessageEvent.model_construct(
        time=1786007349,
        self_id=2357682124,
        post_type="message",
        message_type="group",
        sub_type="normal",
        user_id=2976753330,
        group_id=733291779,
        message_id=1,
        message=Message("漂亮牛艾特我一下"),
        raw_message="漂亮牛艾特我一下",
    )


@pytest.fixture(autouse=True)
def reset_ingress(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    ingress.reset_federate_ingress_win_cache_for_tests()
    ingress_audit.reset_federate_ingress_audit_for_tests()
    monkeypatch.setattr(ingress, "_CANDIDATE_WAIT_SEC", 0.0)
    monkeypatch.setattr(ingress, "record_federate_ingress_audit", lambda **_kwargs: None)
    monkeypatch.setattr(ingress, "federate_ingress_bypass_unified", lambda: False)
    monkeypatch.setattr(ingress.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr(ingress, "federate_ingress_active", lambda: True)
    monkeypatch.setattr(ingress, "load_or_create_deployment_id", lambda: "dep-local")
    if not request.node.name.startswith("test_candidate_registry_"):
        monkeypatch.setattr(
            candidates,
            "read_federate_ingress_candidate_bot_ids_sync",
            lambda **_kwargs: frozenset(),
        )


@pytest.mark.asyncio
async def test_candidate_registers_before_federate_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        candidates,
        "register_federate_ingress_candidate_sync",
        lambda **_kwargs: calls.append("candidate") or True,
    )

    async def claim(*_args, **_kwargs) -> bool:
        calls.append("claim")
        return True

    monkeypatch.setattr(ingress, "try_claim_cross_federate_message", claim)

    assert (
        await ingress.claim_federate_group_message_ingress(
            make_event(), candidate_capability="llm_alias", candidate_bot_id=2357682124
        )
        is True
    )
    assert calls == ["candidate", "claim"]


@pytest.mark.asyncio
async def test_candidate_claim_uses_v2_key_to_avoid_legacy_claimers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingress, "_CANDIDATE_WAIT_SEC", 0.0)
    monkeypatch.setattr(candidates, "register_federate_ingress_candidate_sync", lambda **_kwargs: True)
    monkeypatch.setattr(
        candidates,
        "read_federate_ingress_candidate_bot_ids_sync",
        lambda **_kwargs: frozenset({2357682124}),
    )
    claim = AsyncMock(return_value=True)
    monkeypatch.setattr(ingress, "try_claim_cross_federate_message", claim)

    assert (
        await ingress.claim_federate_group_message_ingress(
            make_event(), candidate_capability="llm_alias", candidate_bot_id=2357682124
        )
        is True
    )

    assert claim.await_args.args[0] == "federate_ingress_v2"


@pytest.mark.asyncio
async def test_non_candidate_hard_trigger_yields_without_federate_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingress, "_CANDIDATE_WAIT_SEC", 0.0)
    monkeypatch.setattr(
        candidates,
        "read_federate_ingress_candidate_bot_ids_sync",
        lambda **_kwargs: frozenset({2357682124}),
    )

    async def claim(*_args, **_kwargs) -> bool:
        raise AssertionError("non-candidate must not claim")

    monkeypatch.setattr(ingress, "try_claim_cross_federate_message", claim)

    assert await ingress.claim_federate_group_message_ingress(make_event(), candidate_wait=True) is False


@pytest.mark.asyncio
async def test_non_candidate_hard_trigger_checks_candidates_without_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    async def must_not_sleep(_delay: float) -> None:
        raise AssertionError("non-candidate ingress must not wait for candidates")

    monkeypatch.setattr(ingress.asyncio, "sleep", must_not_sleep)
    monkeypatch.setattr(
        candidates,
        "read_federate_ingress_candidate_bot_ids_sync",
        lambda **_kwargs: frozenset({2357682124}),
    )

    assert await ingress.claim_federate_group_message_ingress(make_event(), candidate_wait=True) is False


@pytest.mark.asyncio
async def test_multiple_candidates_coalesce_to_one_federate_winner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingress, "_CANDIDATE_WAIT_SEC", 0.0)
    monkeypatch.setattr(candidates, "register_federate_ingress_candidate_sync", lambda **_kwargs: True)
    monkeypatch.setattr(
        candidates,
        "read_federate_ingress_candidate_bot_ids_sync",
        lambda **_kwargs: frozenset({2357682124, 3907360849}),
    )

    async def claim(*_args, **_kwargs) -> bool:
        await asyncio.sleep(0.01)
        return True

    mocked_claim = MagicMock(side_effect=claim)
    monkeypatch.setattr(ingress, "try_claim_cross_federate_message", mocked_claim)

    first, second = await asyncio.gather(
        ingress.claim_federate_group_message_ingress(
            make_event(), candidate_capability="command", candidate_bot_id=2357682124
        ),
        ingress.claim_federate_group_message_ingress(
            make_event(), candidate_capability="llm_alias", candidate_bot_id=3907360849
        ),
    )

    assert (first, second) == (True, False)
    assert mocked_claim.call_count == 1
