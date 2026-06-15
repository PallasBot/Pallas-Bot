from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.platform.ingress.unified_pass import reset_unified_ingress_once_pass_for_tests


@pytest.fixture(autouse=True)
def _reset_unified_ingress_pass() -> None:
    reset_unified_ingress_once_pass_for_tests()


class _FakeEvent:
    def __init__(
        self,
        *,
        group_id: int = 1,
        user_id: int = 2,
        raw_message: str = "hello",
        plain_text: str = "hello",
        time: int = 3,
        message_id: int = 4,
    ) -> None:
        self.group_id = group_id
        self.user_id = user_id
        self.raw_message = raw_message
        self.time = time
        self.message_id = message_id
        self._plain_text = plain_text

    def get_plaintext(self) -> str:
        return self._plain_text


@pytest.mark.asyncio
async def test_build_repeater_event_context_bypasses_command_before_message_tracking(monkeypatch):
    from src.plugins.repeater import event_gate

    event = _FakeEvent(plain_text="牛牛帮助")
    tracked = False
    recorded: list[str] = []

    async def fake_remember(*_args, **_kwargs) -> bool:
        nonlocal tracked
        tracked = True
        return True

    monkeypatch.setattr(event_gate, "repeater_worker_handles_message", lambda _bot_id: True)
    monkeypatch.setattr(event_gate, "is_plugin_command_plaintext", lambda _plain: True)
    monkeypatch.setattr(event_gate, "ingress_fanout_bypasses_claim", lambda _plain: False)
    monkeypatch.setattr(event_gate, "remember_group_message_id", fake_remember)
    monkeypatch.setattr(event_gate, "record_repeater_ingress_event", lambda: recorded.append("event"))
    monkeypatch.setattr(event_gate, "record_repeater_ingress_early_discard", lambda reason: recorded.append(reason))

    result = await event_gate.build_repeater_event_context(100, event)

    assert result is None
    assert tracked is False
    assert recorded == ["event", "plugin_command"]


@pytest.mark.asyncio
async def test_build_repeater_event_context_non_sharding_claims_once(monkeypatch):
    from src.plugins.repeater import event_gate

    event = _FakeEvent(raw_message="[CQ:image,file=x,subType=1]", plain_text="hello")
    calls: list[str] = []

    async def fake_true(*_args, **_kwargs) -> bool:
        return True

    async def fake_false(*_args, **_kwargs) -> bool:
        return False

    async def fake_claim_once(*_args, **_kwargs) -> bool:
        calls.append("once")
        return True

    async def fake_cross_bot(*_args, **_kwargs) -> bool:
        calls.append("cross_bot")
        return True

    monkeypatch.setattr(event_gate, "repeater_worker_handles_message", lambda _bot_id: True)
    monkeypatch.setattr(event_gate, "ingress_fanout_bypasses_claim", lambda _plain: False)
    monkeypatch.setattr(
        "src.features.message_scrub.is_message_scrub_blocked_sync",
        lambda **_: False,
    )
    monkeypatch.setattr(event_gate, "remember_group_message_id", fake_true)
    monkeypatch.setattr(event_gate, "normalize_group_raw_message", lambda raw: f"norm:{raw}")
    monkeypatch.setattr(event_gate, "should_skip_duplicate_group_event", fake_false)
    monkeypatch.setattr(event_gate, "federate_ingress_cached_win", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(event_gate, "claim_federate_group_message_ingress", fake_true)
    monkeypatch.setattr(event_gate.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr(event_gate, "repeater_fanout_enabled", lambda: True)
    monkeypatch.setattr(event_gate, "try_claim_group_message_once", fake_claim_once)
    monkeypatch.setattr(event_gate, "try_claim_cross_bot_message", fake_cross_bot)

    result = await event_gate.build_repeater_event_context(100, event)

    assert result == SimpleNamespace(
        plain_body="hello",
        norm_raw="norm:[CQ:image,file=x,subType=1]",
        sharding_active=False,
    )
    assert calls == ["once"]


@pytest.mark.asyncio
async def test_build_repeater_event_context_sharded_without_fanout_uses_cross_bot_claim(monkeypatch):
    from src.plugins.repeater import event_gate

    event = _FakeEvent(plain_text="hello")
    calls: list[str] = []

    async def fake_true(*_args, **_kwargs) -> bool:
        return True

    async def fake_false(*_args, **_kwargs) -> bool:
        return False

    async def fake_claim_once(*_args, **_kwargs) -> bool:
        calls.append("once")
        return True

    async def fake_cross_bot(*_args, **_kwargs) -> bool:
        calls.append("cross_bot")
        return True

    monkeypatch.setattr(event_gate, "repeater_worker_handles_message", lambda _bot_id: True)
    monkeypatch.setattr(event_gate, "ingress_fanout_bypasses_claim", lambda _plain: False)
    monkeypatch.setattr(
        "src.features.message_scrub.is_message_scrub_blocked_sync",
        lambda **_: False,
    )
    monkeypatch.setattr(event_gate, "remember_group_message_id", fake_true)
    monkeypatch.setattr(event_gate, "normalize_group_raw_message", lambda raw: raw)
    monkeypatch.setattr(event_gate, "should_skip_duplicate_group_event", fake_false)
    monkeypatch.setattr(event_gate, "federate_ingress_cached_win", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(event_gate, "claim_federate_group_message_ingress", fake_true)
    monkeypatch.setattr(event_gate.shard_ctx, "sharding_active", lambda: True)
    monkeypatch.setattr(event_gate, "repeater_fanout_enabled", lambda: False)
    monkeypatch.setattr(event_gate, "try_claim_group_message_once", fake_claim_once)
    monkeypatch.setattr(event_gate, "try_claim_cross_bot_message", fake_cross_bot)

    result = await event_gate.build_repeater_event_context(100, event)

    assert result == SimpleNamespace(plain_body="hello", norm_raw="hello", sharding_active=True)
    assert calls == ["cross_bot"]


@pytest.mark.asyncio
async def test_build_repeater_event_context_records_sharded_cross_bot_claim_loss(monkeypatch):
    from src.plugins.repeater import event_gate

    event = _FakeEvent(plain_text="hello")
    recorded: list[object] = []

    async def fake_true(*_args, **_kwargs) -> bool:
        return True

    async def fake_false(*_args, **_kwargs) -> bool:
        return False

    monkeypatch.setattr(event_gate, "repeater_worker_handles_message", lambda _bot_id: True)
    monkeypatch.setattr(event_gate, "ingress_fanout_bypasses_claim", lambda _plain: False)
    monkeypatch.setattr(
        "src.features.message_scrub.is_message_scrub_blocked_sync",
        lambda **_: False,
    )
    monkeypatch.setattr(event_gate, "remember_group_message_id", fake_true)
    monkeypatch.setattr(event_gate, "normalize_group_raw_message", lambda raw: raw)
    monkeypatch.setattr(event_gate, "should_skip_duplicate_group_event", fake_false)
    monkeypatch.setattr(event_gate, "federate_ingress_cached_win", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(event_gate, "claim_federate_group_message_ingress", fake_true)
    monkeypatch.setattr(event_gate.shard_ctx, "sharding_active", lambda: True)
    monkeypatch.setattr(event_gate, "repeater_fanout_enabled", lambda: False)
    monkeypatch.setattr(event_gate, "try_claim_cross_bot_message", fake_false)
    monkeypatch.setattr(event_gate, "record_repeater_ingress_event", lambda: recorded.append("event"))
    monkeypatch.setattr(event_gate, "record_repeater_ingress_early_discard", lambda reason: recorded.append(reason))
    monkeypatch.setattr(event_gate, "record_repeater_ingress_claim", lambda *, won: recorded.append(("claim", won)))

    result = await event_gate.build_repeater_event_context(100, event)

    assert result is None
    assert recorded == ["event", ("claim", False), "cross_bot_claim"]


@pytest.mark.asyncio
async def test_build_repeater_event_context_keeps_sharded_single_char_plaintext(monkeypatch):
    from src.plugins.repeater import event_gate

    event = _FakeEvent(plain_text="草", raw_message="草")

    async def fake_true(*_args, **_kwargs) -> bool:
        return True

    async def fake_false(*_args, **_kwargs) -> bool:
        return False

    monkeypatch.setattr(event_gate, "repeater_worker_handles_message", lambda _bot_id: True)
    monkeypatch.setattr(event_gate, "ingress_fanout_bypasses_claim", lambda _plain: False)
    monkeypatch.setattr(
        "src.features.message_scrub.is_message_scrub_blocked_sync",
        lambda **_: False,
    )
    monkeypatch.setattr(event_gate, "remember_group_message_id", fake_true)
    monkeypatch.setattr(event_gate, "normalize_group_raw_message", lambda raw: raw)
    monkeypatch.setattr(event_gate, "should_skip_duplicate_group_event", fake_false)
    monkeypatch.setattr(event_gate, "federate_ingress_cached_win", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(event_gate, "claim_federate_group_message_ingress", fake_true)
    monkeypatch.setattr(event_gate.shard_ctx, "sharding_active", lambda: True)
    monkeypatch.setattr(event_gate, "repeater_fanout_enabled", lambda: False)
    monkeypatch.setattr(event_gate, "try_claim_cross_bot_message", fake_true)

    result = await event_gate.build_repeater_event_context(100, event)

    assert result == SimpleNamespace(plain_body="草", norm_raw="草", sharding_active=True)
