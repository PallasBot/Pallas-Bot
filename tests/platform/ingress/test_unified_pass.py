from __future__ import annotations

import pytest

from pallas.core.platform.ingress.unified_pass import (
    mark_unified_ingress_once_won,
    reset_unified_ingress_once_pass_for_tests,
    unified_ingress_once_won,
    unified_ingress_once_won_for_text,
)


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


@pytest.fixture(autouse=True)
def _reset_pass_cache() -> None:
    reset_unified_ingress_once_pass_for_tests()


def test_mark_and_check_unified_ingress_once_won() -> None:
    event = _FakeEvent(plain_text="你好", raw_message="你好")
    assert unified_ingress_once_won(event) is False
    mark_unified_ingress_once_won(event, body="你好")
    assert unified_ingress_once_won(event) is True
    assert unified_ingress_once_won_for_text(1, 2, "你好", 3) is True


@pytest.mark.asyncio
async def test_build_repeater_event_context_skips_claim_when_ingress_once_won(monkeypatch) -> None:
    from packages.repeater import event_gate

    event = _FakeEvent(plain_text="hello")
    mark_unified_ingress_once_won(event, body="hello")
    calls: list[str] = []

    async def fake_true(*_args, **_kwargs) -> bool:
        return True

    async def fake_claim_once(*_args, **_kwargs) -> bool:
        calls.append("once")
        return True

    async def fake_federate(*_args, **_kwargs) -> bool:
        calls.append("federate")
        return True

    monkeypatch.setattr(event_gate, "repeater_worker_handles_message", lambda _bot_id: True)
    monkeypatch.setattr(event_gate, "ingress_fanout_bypasses_claim", lambda _plain: False)
    monkeypatch.setattr(
        "pallas.product.message_scrub.is_message_scrub_blocked_sync",
        lambda **_: False,
    )
    monkeypatch.setattr(event_gate, "remember_group_message_id", fake_true)
    monkeypatch.setattr(event_gate, "normalize_group_raw_message", lambda raw: raw)

    async def fake_not_dup(*_args, **_kwargs) -> bool:
        return False

    monkeypatch.setattr(event_gate, "should_skip_duplicate_group_event", fake_not_dup)
    monkeypatch.setattr(event_gate, "federate_ingress_cached_win", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(event_gate, "claim_federate_group_message_ingress", fake_federate)
    monkeypatch.setattr(event_gate.shard_ctx, "sharding_active", lambda: False)
    monkeypatch.setattr(event_gate, "try_claim_group_message_once", fake_claim_once)

    result = await event_gate.build_repeater_event_context(100, event)

    assert result is not None
    assert result.plain_body == "hello"
    assert calls == []
