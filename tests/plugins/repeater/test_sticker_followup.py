from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def test_repeater_sticker_followup_config_defaults() -> None:
    from packages.repeater.config import Config

    cfg = Config()

    assert cfg.sticker_followup_rate == pytest.approx(0.12)
    assert cfg.sticker_followup_cooldown_sec == 90
    assert cfg.sticker_followup_max_per_hour == 12


@pytest.mark.asyncio
async def test_repeater_sticker_followup_sends_random_cached_image_after_plain_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.repeater import sticker_followup

    bot = MagicMock()
    bot.call_api = AsyncMock(return_value={"message_id": 2})
    cfg = SimpleNamespace(
        sticker_followup_rate=1.0,
        sticker_followup_cooldown_sec=90,
        sticker_followup_max_per_hour=8,
    )
    monkeypatch.setattr(sticker_followup, "get_recent_images", AsyncMock(return_value=[("[CQ:image,file=a]", b"a")]))
    monkeypatch.setattr(sticker_followup, "should_schedule_outgoing_sticker", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sticker_followup, "should_send_repeater_image", lambda *_args, **_kwargs: True)

    assert await sticker_followup.maybe_send_repeater_sticker_followup(bot, 100, "笑死", cfg=cfg)
    bot.call_api.assert_awaited_once()


@pytest.mark.asyncio
async def test_repeater_sticker_followup_skips_reply_that_already_has_image(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater import sticker_followup

    cfg = SimpleNamespace(
        sticker_followup_rate=1.0,
        sticker_followup_cooldown_sec=90,
        sticker_followup_max_per_hour=8,
    )
    get_recent_images = AsyncMock()
    monkeypatch.setattr(sticker_followup, "get_recent_images", get_recent_images)

    assert not await sticker_followup.maybe_send_repeater_sticker_followup(
        MagicMock(), 100, "[CQ:image,file=already.jpg]", cfg=cfg
    )
    get_recent_images.assert_not_awaited()


@pytest.mark.asyncio
async def test_repeater_sticker_followup_skips_non_plain_text_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater import sticker_followup

    cfg = SimpleNamespace(
        sticker_followup_rate=1.0,
        sticker_followup_cooldown_sec=90,
        sticker_followup_max_per_hour=8,
    )
    get_recent_images = AsyncMock()
    monkeypatch.setattr(sticker_followup, "get_recent_images", get_recent_images)

    assert not await sticker_followup.maybe_send_repeater_sticker_followup(
        MagicMock(), 100, "[CQ:face,id=14]", cfg=cfg
    )
    get_recent_images.assert_not_awaited()


@pytest.mark.asyncio
async def test_repeater_scheduler_uses_its_own_sticker_followup(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater.handlers import scheduler

    bot = MagicMock()
    bot.call_api = AsyncMock(return_value={"message_id": 2})
    send_sticker = AsyncMock(return_value=True)
    monkeypatch.setattr(scheduler, "should_pause_tasks", lambda: False)
    monkeypatch.setattr(scheduler, "repeater_scheduler_runs_on_worker", lambda: True)
    monkeypatch.setattr(scheduler.Chat, "speak", AsyncMock(return_value=(200, 100, ["我来了"], None)))
    monkeypatch.setattr(scheduler, "get_bot", lambda _bot_id: bot)
    monkeypatch.setattr("packages.repeater.sticker_followup.maybe_send_repeater_sticker_followup", send_sticker)

    await scheduler.speak_up()

    send_sticker.assert_awaited_once_with(bot, 100, "我来了")
