from __future__ import annotations

import pytest


def test_outgoing_sticker_followup_can_be_suppressed_for_one_send() -> None:
    from pallas.product.llm.sticker_followup import (
        outgoing_sticker_followup_suppressed,
        should_handle_outgoing_sticker_followup,
        suppress_outgoing_sticker_followup,
    )

    assert not outgoing_sticker_followup_suppressed()
    assert should_handle_outgoing_sticker_followup(None, "send_group_msg")
    with suppress_outgoing_sticker_followup():
        assert outgoing_sticker_followup_suppressed()
        assert not should_handle_outgoing_sticker_followup(None, "send_group_msg")
    assert not outgoing_sticker_followup_suppressed()


def test_sticker_followup_cooldown_and_recent_image_deduplication() -> None:
    from pallas.product.llm.sticker_followup import (
        note_repeater_image_sent,
        reset_repeater_image_followup_state_for_tests,
        should_send_repeater_image,
    )

    reset_repeater_image_followup_state_for_tests()
    assert should_send_repeater_image(42, "[CQ:image,file=a.image]", cooldown_sec=60, now=100.0)

    note_repeater_image_sent(42, "[CQ:image,file=a.image]", now=100.0)

    assert not should_send_repeater_image(42, "[CQ:image,file=b.image]", cooldown_sec=60, now=120.0)
    assert not should_send_repeater_image(42, "[CQ:image,file=a.image]", cooldown_sec=0, now=200.0)
    assert should_send_repeater_image(42, "[CQ:image,file=b.image]", cooldown_sec=60, now=200.0)


def test_sticker_followup_tracks_recent_content_hashes_across_cache_keys() -> None:
    from pallas.product.llm.sticker_followup import (
        note_repeater_image_sent,
        recent_repeater_image_hashes,
        reset_repeater_image_followup_state_for_tests,
    )

    reset_repeater_image_followup_state_for_tests()
    note_repeater_image_sent(42, "[CQ:image,file=old-key]", content_hash="a" * 64, now=100.0)

    assert recent_repeater_image_hashes(42) == ("a" * 64,)


def test_outgoing_text_followup_accepts_command_result_and_applies_group_cooldown() -> None:
    from pallas.product.llm.sticker_followup import (
        reset_repeater_image_followup_state_for_tests,
        should_schedule_outgoing_sticker,
    )

    reset_repeater_image_followup_state_for_tests()
    assert should_schedule_outgoing_sticker(42, "抽到了！", cooldown_sec=90, max_per_hour=8, now=100.0)
    assert not should_schedule_outgoing_sticker(42, "再抽一次", cooldown_sec=90, max_per_hour=8, now=150.0)
    assert should_schedule_outgoing_sticker(42, "再抽一次", cooldown_sec=90, max_per_hour=8, now=191.0)


def test_outgoing_text_followup_applies_hourly_quota() -> None:
    from pallas.product.llm.sticker_followup import (
        reset_repeater_image_followup_state_for_tests,
        should_schedule_outgoing_sticker,
    )

    reset_repeater_image_followup_state_for_tests()
    assert should_schedule_outgoing_sticker(42, "第一条", cooldown_sec=0, max_per_hour=1, now=100.0)
    assert not should_schedule_outgoing_sticker(42, "第二条", cooldown_sec=0, max_per_hour=1, now=101.0)


def test_outgoing_text_followup_rejects_sensitive_result() -> None:
    from pallas.product.llm.sticker_followup import should_schedule_outgoing_sticker

    assert not should_schedule_outgoing_sticker(
        42,
        "权限不足，无法执行此操作",
        cooldown_sec=90,
        max_per_hour=8,
        now=100.0,
    )


@pytest.mark.asyncio
async def test_outgoing_followup_preserves_llm_origin_without_changing_ordinary_origin(monkeypatch) -> None:
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from nonebot.adapters import Bot as BaseBot

    from pallas.product.llm import sticker_followup

    hooks = []
    monkeypatch.setattr(BaseBot, "on_called_api", lambda hook: hooks.append(hook) or hook)
    monkeypatch.setattr(sticker_followup, "_OUTGOING_HOOK_BOUND", False)
    monkeypatch.setattr(
        "pallas.product.llm.config.get_llm_config",
        lambda: SimpleNamespace(llm_chat_sticker_enabled=True, llm_chat_sticker_cooldown_sec=0),
    )
    monkeypatch.setattr(sticker_followup, "should_schedule_outgoing_sticker", lambda *_args, **_kwargs: True)
    origins = []

    async def send_followup(*_args, llm_origin: bool = False, **_kwargs) -> None:
        origins.append(llm_origin)

    monkeypatch.setattr(sticker_followup, "send_outgoing_sticker_followup", send_followup)
    sticker_followup.bind_outgoing_sticker_followup()
    hook = hooks[0]
    bot = MagicMock(self_id=111)
    args = (bot, None, "send_group_msg", {"group_id": 222, "message": "普通文本"}, None)

    with sticker_followup.llm_sticker_followup_origin():
        await hook(*args)
    await hook(*args)
    await asyncio.sleep(0)

    assert origins == [True, False]
