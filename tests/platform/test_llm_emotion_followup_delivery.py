from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image, ImageSequence

from pallas.core.platform.ai_callback.task_types import LLM_CHAT_TASK_TYPE
from pallas.product.llm import delivery


def test_prepare_sticker_image_shrinks_large_png_without_upscaling_small_png() -> None:
    large = BytesIO()
    Image.new("RGBA", (400, 200), "red").save(large, format="PNG")
    small = BytesIO()
    Image.new("RGBA", (80, 40), "blue").save(small, format="PNG")

    resized = delivery.prepare_sticker_image(large.getvalue())

    with Image.open(BytesIO(resized)) as image:
        assert image.size == (160, 80)
    assert delivery.prepare_sticker_image(small.getvalue()) == small.getvalue()


def test_prepare_sticker_image_preserves_animated_gif_frames_and_duration() -> None:
    first = Image.new("RGBA", (320, 160), "red")
    second = Image.new("RGBA", (320, 160), "blue")
    source = BytesIO()
    first.save(source, format="GIF", save_all=True, append_images=[second], duration=[80, 120], loop=0)

    resized = delivery.prepare_sticker_image(source.getvalue())

    with Image.open(BytesIO(resized)) as image:
        frames = [frame.copy() for frame in ImageSequence.Iterator(image)]
        assert image.size == (160, 80)
        assert image.n_frames == 2
        assert [frame.info["duration"] for frame in frames] == [80, 120]


@pytest.mark.asyncio
async def test_llm_delivery_sends_repeater_image_after_model_requests_sticker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = MagicMock()
    monkeypatch.setattr(delivery, "send_group_message", AsyncMock(return_value=True))
    send_image = AsyncMock(return_value=True)
    monkeypatch.setattr(delivery, "send_repeater_emotion_image", send_image)
    monkeypatch.setattr(
        delivery,
        "get_llm_config",
        lambda: MagicMock(
            llm_reply_postprocess_enabled=False,
            llm_reply_typo_enabled=False,
            llm_reply_typo_rate=0,
            llm_reply_split_enabled=False,
            llm_reply_split_max_chars=36,
            llm_reply_trim_terminal_period_enabled=False,
            llm_reply_trim_terminal_period_rate=0,
            llm_reply_mention_cooldown_sec=0,
            llm_chat_sticker_enabled=True,
        ),
    )
    monkeypatch.setattr(delivery, "should_attach_repeater_image", lambda task, reply, raw: True)

    await delivery.deliver_llm_callback_success(
        "task-emotion",
        {
            "task_type": LLM_CHAT_TASK_TYPE,
            "group_id": 222,
            "user_id": 333,
            "bot_id": 111,
            "user_text": "牛牛我喜欢你",
        },
        bot=bot,
        group_id=222,
        bot_id=111,
        bot_id_str="111",
        text='{"reply":"我听到了。","sticker":"send"}',
        parsed_agent_trace=None,
        history_summary=None,
        history_keep_messages=None,
    )

    send_image.assert_awaited_once_with(bot, 222, 111, 333, "牛牛我喜欢你")


@pytest.mark.asyncio
async def test_llm_delivery_keeps_text_when_no_repeater_image_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = MagicMock()
    send_text = AsyncMock(return_value=True)
    monkeypatch.setattr(delivery, "send_group_message", send_text)
    monkeypatch.setattr(delivery, "send_repeater_emotion_image", AsyncMock(return_value=False))
    monkeypatch.setattr(
        delivery,
        "get_llm_config",
        lambda: MagicMock(
            llm_reply_postprocess_enabled=False,
            llm_reply_typo_enabled=False,
            llm_reply_typo_rate=0,
            llm_reply_split_enabled=False,
            llm_reply_split_max_chars=36,
            llm_reply_trim_terminal_period_enabled=False,
            llm_reply_trim_terminal_period_rate=0,
            llm_reply_mention_cooldown_sec=0,
            llm_chat_sticker_enabled=True,
        ),
    )
    monkeypatch.setattr(delivery, "should_attach_repeater_image", lambda task, reply, raw: True)

    reply_text, text_delivered, delivered = await delivery.deliver_llm_callback_success(
        "task-no-image",
        {"task_type": LLM_CHAT_TASK_TYPE, "group_id": 222, "user_id": 333, "bot_id": 111, "user_text": "我想你"},
        bot=bot,
        group_id=222,
        bot_id=111,
        bot_id_str="111",
        text="我也在。",
        parsed_agent_trace=None,
        history_summary=None,
        history_keep_messages=None,
    )

    assert (reply_text, text_delivered, delivered) == ("我也在。", True, True)
    send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_repeater_image_sender_allows_cross_group_cached_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater.model import Chat
    from pallas.core.shared.utils import media_cache

    bot = MagicMock()
    bot.call_api = AsyncMock(return_value={"message_id": 1})
    monkeypatch.setattr(
        Chat,
        "find_reply_bundle",
        AsyncMock(
            return_value=SimpleNamespace(
                reply_source="cross_group",
                answer_list=["[CQ:image,file=example.jpg]"],
            )
        ),
    )
    monkeypatch.setattr(media_cache, "get_image", AsyncMock(return_value=b"cached-image"))

    assert await delivery.send_repeater_emotion_image(bot, 222, 111, 333, "太好笑了")
    bot.call_api.assert_awaited_once()


@pytest.mark.asyncio
async def test_repeater_image_sender_skips_uncached_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater.model import Chat
    from pallas.core.shared.utils import media_cache

    bot = MagicMock()
    bot.call_api = AsyncMock()
    monkeypatch.setattr(
        Chat,
        "find_reply_bundle",
        AsyncMock(return_value=SimpleNamespace(reply_source="same_group", answer_list=["[CQ:image,file=example.jpg]"])),
    )
    monkeypatch.setattr(media_cache, "get_image", AsyncMock(return_value=None))

    assert not await delivery.send_repeater_emotion_image(bot, 222, 111, 333, "太好笑了")
    bot.call_api.assert_not_awaited()


@pytest.mark.asyncio
async def test_cached_sticker_sender_uses_cached_image_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.shared.utils import media_cache

    bot = MagicMock()
    bot.call_api = AsyncMock(return_value={"message_id": 1})
    monkeypatch.setattr(media_cache, "get_latest_image", AsyncMock(return_value=b"cached-image"), raising=False)

    assert await delivery.send_cached_sticker_image(bot, 222)
    bot.call_api.assert_awaited_once()
