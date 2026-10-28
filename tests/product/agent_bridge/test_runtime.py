"""Focused tests for the MaiBot bridge runtime scope query and reply callback."""

from types import SimpleNamespace

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent

from pallas.product.agent_bridge import runtime
from pallas.product.agent_bridge.config import MaiBotBridgeConfig

BOT_ID = 10001
OTHER_BOT = 10002
GROUP_ID = 700001
OTHER_GROUP = 700002


def _config(**overrides):
    base = {
        "enabled": True,
        "url": "ws://127.0.0.1:18000/ws",
        "bot_id": BOT_ID,
        "group_ids": frozenset({GROUP_ID}),
        "platform": "pallas-qq",
        "token": "",
    }
    base.update(overrides)
    return MaiBotBridgeConfig(**base)


def _arm(monkeypatch, owner=None, live="same"):
    owner = owner or _config()
    monkeypatch.setattr(runtime, "_owner_config", owner)
    if live == "same":
        monkeypatch.setattr(runtime, "_live_config_or_none", lambda: owner)
    else:
        monkeypatch.setattr(runtime, "_live_config_or_none", lambda: live)


def _event(*, user_id=7, group_id=GROUP_ID):
    return GroupMessageEvent.model_validate({
        "time": 1800000000,
        "self_id": BOT_ID,
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "message_id": 123,
        "group_id": group_id,
        "user_id": user_id,
        "message": [{"type": "text", "data": {"text": "synthetic text"}}],
        "raw_message": "synthetic text",
        "font": 0,
        "sender": {"user_id": user_id, "nickname": "synthetic user", "role": "member"},
    })


def test_scope_binds_both_bot_and_group(monkeypatch):
    _arm(monkeypatch)
    assert runtime.bridge_owns(BOT_ID, GROUP_ID) is True
    assert runtime.bridge_owns(OTHER_BOT, GROUP_ID) is False  # another account in the same group
    assert runtime.bridge_owns(BOT_ID, OTHER_GROUP) is False


def test_scope_retained_when_live_config_invalid(monkeypatch):
    _arm(monkeypatch, live=None)
    assert runtime.bridge_owns(BOT_ID, GROUP_ID) is True


def test_ownership_ignores_live_disable_and_group_removal(monkeypatch):
    for live in (_config(enabled=False), _config(group_ids=frozenset()), _config(bot_id=OTHER_BOT)):
        _arm(monkeypatch, live=live)
        assert runtime.bridge_owns(BOT_ID, GROUP_ID) is True
        assert runtime.bridge_suppresses(BOT_ID, GROUP_ID) is True


def test_communication_allowed_follows_live_config(monkeypatch):
    _arm(monkeypatch)
    assert runtime.communication_allowed(BOT_ID, GROUP_ID) is True
    for live in (_config(enabled=False), _config(group_ids=frozenset()), _config(bot_id=OTHER_BOT), None):
        _arm(monkeypatch, live=live)
        assert runtime.communication_allowed(BOT_ID, GROUP_ID) is False


def test_suppresses_requires_explicit_bot(monkeypatch):
    _arm(monkeypatch)
    assert runtime.bridge_suppresses(BOT_ID, GROUP_ID) is True
    assert runtime.bridge_suppresses(OTHER_BOT, GROUP_ID) is False
    assert runtime.bridge_suppresses(None, GROUP_ID) is False


def test_live_config_tracks_raw_value_changes(monkeypatch):
    runtime.clear_bridge_runtime_cache()
    values: dict[str, str | None] = {"MAIBOT_BRIDGE_ENABLED": "false"}
    monkeypatch.setattr(runtime, "repo_env_raw_value", lambda key: values.get(key))
    assert runtime.live_bridge_config().enabled is False
    values.update({
        "MAIBOT_BRIDGE_ENABLED": "true",
        "MAIBOT_BRIDGE_URL": "ws://host/ws",
        "MAIBOT_BRIDGE_BOT_ID": "10001",
        "MAIBOT_BRIDGE_GROUP_IDS": "[700001]",
        "MAIBOT_BRIDGE_PLATFORM": "pallas-qq",
    })
    assert runtime.live_bridge_config().enabled is True


async def test_group_ban_refusal_uses_ban_gate_on_acl_fallback(monkeypatch):
    async def evaluate_acl(**_kwargs):
        return SimpleNamespace(source="fallback", allow=True)

    async def ban_gate(_group_id):
        return True

    monkeypatch.setattr("pallas.core.perm.acl.evaluate_acl", evaluate_acl)
    monkeypatch.setattr("packages.blacklist.ban_gate.query_group_ban_status_for_gate", ban_gate)
    assert await runtime.group_ban_refusal(BOT_ID, GROUP_ID) == "group_banned"


async def test_group_ban_refusal_honours_decisive_acl_deny(monkeypatch):
    async def evaluate_acl(**_kwargs):
        return SimpleNamespace(source="rule", allow=False)

    async def ban_gate(_group_id):
        return False

    monkeypatch.setattr("pallas.core.perm.acl.evaluate_acl", evaluate_acl)
    monkeypatch.setattr("packages.blacklist.ban_gate.query_group_ban_status_for_gate", ban_gate)
    assert await runtime.group_ban_refusal(BOT_ID, GROUP_ID) == "group_banned"


def _install_gates(monkeypatch, *, disabled=False, sleeping=False, ban_allow=True, scrub_blocked=False, receipt=None):
    async def is_plugin_disabled(*_args, **_kwargs):
        return disabled

    class FakeBotConfig:
        def __init__(self, *_args, **_kwargs):
            pass

        async def is_sleep(self):
            return sleeping

    async def evaluate_acl(**_kwargs):
        return SimpleNamespace(source="rule", allow=ban_allow)

    async def query_group_ban_status_for_gate(_group_id):
        return not ban_allow

    async def is_message_scrub_blocked_async(**_kwargs):
        return scrub_blocked

    class FakeBot:
        self_id = str(BOT_ID)

    async def send_group_message_with_receipt(_bot, _group_id, _text, **_kwargs):
        return receipt if receipt is not None else SimpleNamespace(delivered=True, message_id=4242)

    monkeypatch.setattr("packages.help.plugin_manager.is_plugin_disabled", is_plugin_disabled)
    monkeypatch.setattr("pallas.core.foundation.config.BotConfig", FakeBotConfig)
    monkeypatch.setattr("pallas.core.perm.acl.evaluate_acl", evaluate_acl)
    monkeypatch.setattr("packages.blacklist.ban_gate.query_group_ban_status_for_gate", query_group_ban_status_for_gate)
    monkeypatch.setattr("pallas.product.message_scrub.is_message_scrub_blocked_async", is_message_scrub_blocked_async)
    monkeypatch.setattr(runtime, "get_bot", lambda _id: FakeBot())
    monkeypatch.setattr(
        "pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt",
        send_group_message_with_receipt,
    )


async def test_callback_refuses_when_group_revoked(monkeypatch):
    _arm(monkeypatch, live=_config(group_ids=frozenset({GROUP_ID})))
    with pytest.raises(runtime.BridgeSendRefusedError):
        await runtime.bridge_send_reply(BOT_ID, OTHER_GROUP, "hi")


async def test_callback_refuses_when_disabled(monkeypatch):
    _arm(monkeypatch, live=_config(enabled=False))
    with pytest.raises(runtime.BridgeSendRefusedError):
        await runtime.bridge_send_reply(BOT_ID, GROUP_ID, "hi")


async def test_callback_delivers_and_returns_real_message_id(monkeypatch):
    _arm(monkeypatch)
    _install_gates(monkeypatch)
    assert await runtime.bridge_send_reply(BOT_ID, GROUP_ID, "hi") == 4242


async def test_callback_refuses_without_a_real_receipt(monkeypatch):
    _arm(monkeypatch)
    _install_gates(monkeypatch, receipt=SimpleNamespace(delivered=True, message_id=None))
    with pytest.raises(runtime.BridgeSendRefusedError):
        await runtime.bridge_send_reply(BOT_ID, GROUP_ID, "hi")


@pytest.mark.parametrize(
    "gates", [{"disabled": True}, {"sleeping": True}, {"ban_allow": False}, {"scrub_blocked": True}]
)
async def test_callback_refuses_on_each_gate(monkeypatch, gates):
    _arm(monkeypatch)
    _install_gates(monkeypatch, **gates)
    with pytest.raises(runtime.BridgeSendRefusedError):
        await runtime.bridge_send_reply(BOT_ID, GROUP_ID, "hi")


class _FakeBridge:
    def __init__(self):
        self.connected = True
        self.forwarded: list[dict] = []

    async def forward_event(self, payload, *, command_traffic):
        self.forwarded.append(payload)


def _patch_forward(monkeypatch, *, scrub_blocked=False, scrub_raises=False):
    bridge = _FakeBridge()
    monkeypatch.setattr(runtime, "_bridge", bridge)
    monkeypatch.setattr(runtime, "group_output_refusal", _no_refusal)
    monkeypatch.setattr("pallas.core.perm.check.satisfies_command_permission", _allow_async)

    async def scrub(**_kwargs):
        if scrub_raises:
            raise RuntimeError("synthetic scrub failure")
        return scrub_blocked

    monkeypatch.setattr("pallas.product.message_scrub.is_message_scrub_blocked_async", scrub)
    return bridge


async def _allow_async(*_args, **_kwargs):
    return True


async def _no_refusal(*_args, **_kwargs):
    return None


async def test_forward_converts_event_to_plain_onebot_dict(monkeypatch):
    _arm(monkeypatch)
    bridge = _patch_forward(monkeypatch)
    bot = SimpleNamespace(self_id=str(BOT_ID))
    assert await runtime.forward_owned_event(bot, _event(), command_traffic=False) is True
    payload = bridge.forwarded[0]
    assert isinstance(payload, dict)
    assert payload["post_type"] == "message"
    assert payload["message_type"] == "group"
    assert payload["self_id"] == BOT_ID
    assert payload["group_id"] == GROUP_ID
    assert payload["message_id"] == 123


async def test_forward_rejects_the_bound_bot_own_message(monkeypatch):
    _arm(monkeypatch)
    bridge = _patch_forward(monkeypatch)
    bot = SimpleNamespace(self_id=str(BOT_ID))
    assert await runtime.forward_owned_event(bot, _event(user_id=BOT_ID), command_traffic=False) is False
    assert bridge.forwarded == []


async def test_forward_rejects_another_bot_same_group(monkeypatch):
    _arm(monkeypatch)
    bridge = _patch_forward(monkeypatch)
    bot = SimpleNamespace(self_id=str(OTHER_BOT))
    assert await runtime.forward_owned_event(bot, _event(), command_traffic=False) is False
    assert bridge.forwarded == []


@pytest.mark.parametrize("live", [_config(enabled=False), _config(group_ids=frozenset()), None])
async def test_forward_refused_when_live_revoked_but_still_owned(monkeypatch, live):
    _arm(monkeypatch, live=live)
    bridge = _patch_forward(monkeypatch)
    bot = SimpleNamespace(self_id=str(BOT_ID))
    assert runtime.bridge_owns(BOT_ID, GROUP_ID) is True
    assert await runtime.forward_owned_event(bot, _event(), command_traffic=False) is False
    assert bridge.forwarded == []


async def test_forward_refused_when_remote_scrub_blocks(monkeypatch):
    _arm(monkeypatch)
    bridge = _patch_forward(monkeypatch, scrub_blocked=True)
    bot = SimpleNamespace(self_id=str(BOT_ID))
    assert await runtime.forward_owned_event(bot, _event(), command_traffic=False) is False
    assert bridge.forwarded == []


async def test_forward_refused_when_remote_scrub_raises(monkeypatch):
    _arm(monkeypatch)
    bridge = _patch_forward(monkeypatch, scrub_raises=True)
    bot = SimpleNamespace(self_id=str(BOT_ID))
    assert await runtime.forward_owned_event(bot, _event(), command_traffic=False) is False
    assert bridge.forwarded == []


def _multi_config(**overrides):
    base = {
        "enabled": True,
        "url": "ws://127.0.0.1:18000/ws",
        "bot_id": 0,
        "bot_ids": frozenset({BOT_ID, OTHER_BOT}),
        "group_ids": frozenset({GROUP_ID}),
        "platform": "pallas-qq",
        "token": "",
    }
    base.update(overrides)
    return MaiBotBridgeConfig(**base)


def test_multi_account_owns_every_snapshot_account(monkeypatch):
    _arm(monkeypatch, owner=_multi_config())
    assert runtime.bridge_owns(BOT_ID, GROUP_ID) is True
    assert runtime.bridge_owns(OTHER_BOT, GROUP_ID) is True
    assert runtime.bridge_owns_account(BOT_ID) is True
    assert runtime.bridge_owns_account(OTHER_BOT) is True
    assert runtime.bridge_owns_account(99999) is False


def test_multi_account_communication_follows_live_set(monkeypatch):
    _arm(monkeypatch, owner=_multi_config(), live=_multi_config(bot_ids=frozenset({BOT_ID})))
    assert runtime.communication_allowed(BOT_ID, GROUP_ID) is True
    assert runtime.communication_allowed(OTHER_BOT, GROUP_ID) is False  # live removed it


def test_bridge_status_reports_bot_ids_without_url(monkeypatch):
    _arm(monkeypatch, owner=_multi_config())
    status = runtime.bridge_status()
    assert status["bot_ids"] == [BOT_ID, OTHER_BOT]
    assert "url" not in status
    assert status["url_configured"] is True


async def test_forward_filters_managed_peer_account(monkeypatch):
    _arm(monkeypatch, owner=_multi_config())
    bridge = _patch_forward(monkeypatch)
    bot = SimpleNamespace(self_id=str(BOT_ID))
    assert await runtime.forward_owned_event(bot, _event(user_id=OTHER_BOT), command_traffic=False) is False
    assert bridge.forwarded == []
    assert await runtime.forward_owned_event(bot, _event(user_id=7), command_traffic=False) is True
    assert len(bridge.forwarded) == 1
