from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pallas.api.platform import group_admin_owner_ingress_route
from pallas.core.platform.ingress import group_admin_owner as policy


def test_group_admin_owner_route_is_public_metadata() -> None:
    assert group_admin_owner_ingress_route(passive=True) == {
        "passive": True,
        "required_bot_capability": "group_admin",
    }


def test_required_capability_comes_from_matched_route(monkeypatch) -> None:
    monkeypatch.setattr(
        policy,
        "resolve_message_route",
        lambda _plain: SimpleNamespace(matched_modules=frozenset({"roulette"})),
    )
    monkeypatch.setattr(
        policy,
        "get_route_index",
        lambda: SimpleNamespace(required_bot_capabilities={"roulette": "group_admin"}),
    )

    assert policy.required_bot_capability_for_plain("牛牛轮盘") == "group_admin"


def test_unmatched_plaintext_has_no_required_capability(monkeypatch) -> None:
    monkeypatch.setattr(
        policy,
        "resolve_message_route",
        lambda _plain: SimpleNamespace(matched_modules=frozenset()),
    )
    monkeypatch.setattr(
        policy,
        "get_route_index",
        lambda: SimpleNamespace(required_bot_capabilities={"roulette": "group_admin"}),
    )

    assert policy.required_bot_capability_for_plain("普通聊天") is None


@pytest.mark.asyncio
async def test_unknown_owner_does_not_block(monkeypatch) -> None:
    monkeypatch.setattr(policy, "required_bot_capability_for_plain", lambda _plain: "group_admin")
    monkeypatch.setattr(policy, "resolve_local_connected_bots_in_group", AsyncMock(return_value=[2]))
    monkeypatch.setattr(policy, "warm_local_group_admin_observations", AsyncMock())
    monkeypatch.setattr(policy, "federate_group_admin_owner", lambda *_args, **_kwargs: None)

    decision = await policy.group_admin_owner_ingress_decision(1, 2, "牛牛轮盘")

    assert decision.passes is True
    assert decision.fallback_to_fanout is True


@pytest.mark.asyncio
async def test_known_owner_allows_only_the_selected_local_bot(monkeypatch) -> None:
    monkeypatch.setattr(policy, "required_bot_capability_for_plain", lambda _plain: "group_admin")
    connected_bots = AsyncMock(return_value=[2, 3])
    monkeypatch.setattr(policy, "resolve_local_connected_bots_in_group", connected_bots)
    monkeypatch.setattr(policy, "warm_local_group_admin_observations", AsyncMock())
    monkeypatch.setattr(policy, "_local_deployment_id", lambda: "dep-local")
    monkeypatch.setattr(
        policy,
        "federate_group_admin_owner",
        lambda *_args, **_kwargs: policy.GroupAdminOwner("dep-local", 2),
    )

    assert (await policy.group_admin_owner_ingress_decision(1, 2, "牛牛轮盘")).passes is True
    assert (await policy.group_admin_owner_ingress_decision(1, 3, "牛牛轮盘")).passes is False
    connected_bots.assert_awaited_with(1, force_probe=True)
