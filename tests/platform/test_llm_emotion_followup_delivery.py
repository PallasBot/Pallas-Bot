from __future__ import annotations

import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image, ImageSequence

from pallas.core.platform.ai_callback.task_types import LLM_CHAT_TASK_TYPE
from pallas.product.llm import delivery


def test_prepare_sticker_image_shrinks_large_png_without_upscaling_small_png() -> None:
    large = BytesIO()
    Image.new("RGBA", (640, 320), "red").save(large, format="PNG")
    small = BytesIO()
    Image.new("RGBA", (80, 40), "blue").save(small, format="PNG")

    resized = delivery.prepare_sticker_image(large.getvalue())

    with Image.open(BytesIO(resized)) as image:
        assert image.size == (320, 160)
    assert delivery.prepare_sticker_image(small.getvalue()) == small.getvalue()


def test_prepare_sticker_image_preserves_animated_gif_frames_and_duration() -> None:
    first = Image.new("RGBA", (640, 320), "red")
    second = Image.new("RGBA", (640, 320), "blue")
    source = BytesIO()
    first.save(source, format="GIF", save_all=True, append_images=[second], duration=[80, 120], loop=0)

    resized = delivery.prepare_sticker_image(source.getvalue())

    with Image.open(BytesIO(resized)) as image:
        frames = [frame.copy() for frame in ImageSequence.Iterator(image)]
        assert image.size == (320, 160)
        assert image.n_frames == 2
        assert [frame.info["duration"] for frame in frames] == [80, 120]


@pytest.mark.asyncio
async def test_llm_delivery_schedules_structured_sticker_after_successful_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = MagicMock()

    async def send_text(*_args, **_kwargs):
        from pallas.product.llm.sticker_followup import outgoing_sticker_followup_suppressed

        assert outgoing_sticker_followup_suppressed()
        return type("Receipt", (), {"delivered": True, "message_id": 1})()

    monkeypatch.setattr("pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt", send_text)
    send_image = AsyncMock(return_value=True)
    monkeypatch.setattr(delivery, "send_repeater_emotion_image", send_image)
    schedule = MagicMock(return_value=True)
    monkeypatch.setattr("pallas.product.llm.sticker_followup.should_schedule_outgoing_sticker", schedule)
    monkeypatch.setattr(
        delivery,
        "get_llm_config",
        lambda: MagicMock(
            llm_reply_postprocess_enabled=False,
            llm_reply_typo_enabled=False,
            llm_reply_typo_rate=0,
            llm_reply_trim_terminal_period_enabled=False,
            llm_reply_trim_terminal_period_rate=0,
            llm_reply_mention_cooldown_sec=0,
            llm_chat_sticker_enabled=True,
            llm_chat_sticker_cooldown_sec=90,
            llm_chat_sticker_max_per_hour=8,
        ),
    )
    reply_text, text_delivered, delivered = await delivery.deliver_llm_callback_success(
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

    assert (reply_text, text_delivered, delivered) == ("我听到了。", True, True)
    await asyncio.sleep(0)
    schedule.assert_called_once_with(222, "我听到了。", cooldown_sec=90, max_per_hour=8)
    send_image.assert_awaited_once_with(bot, 222, 111, 333, "send")


@pytest.mark.asyncio
async def test_llm_delivery_skips_sensitive_structured_sticker_at_global_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = MagicMock()

    async def send_text(*_args, **_kwargs):
        from pallas.product.llm.sticker_followup import outgoing_sticker_followup_suppressed

        assert outgoing_sticker_followup_suppressed()
        return type("Receipt", (), {"delivered": True, "message_id": 1})()

    monkeypatch.setattr("pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt", send_text)
    send_image = AsyncMock(return_value=True)
    monkeypatch.setattr(delivery, "send_repeater_emotion_image", send_image)
    monkeypatch.setattr(
        delivery,
        "get_llm_config",
        lambda: MagicMock(
            llm_reply_postprocess_enabled=False,
            llm_reply_typo_enabled=False,
            llm_reply_typo_rate=0,
            llm_reply_trim_terminal_period_enabled=False,
            llm_reply_trim_terminal_period_rate=0,
            llm_reply_mention_cooldown_sec=0,
            llm_chat_sticker_enabled=True,
            llm_chat_sticker_cooldown_sec=90,
            llm_chat_sticker_max_per_hour=8,
        ),
    )

    assert await delivery.deliver_llm_callback_success(
        "task-structured-rejected",
        {"task_type": LLM_CHAT_TASK_TYPE, "group_id": 222, "user_id": 333, "bot_id": 111},
        bot=bot,
        group_id=222,
        bot_id=111,
        bot_id_str="111",
        text='{"reply":"权限不足。","sticker":"send"}',
        parsed_agent_trace=None,
        history_summary=None,
        history_keep_messages=None,
    ) == ("权限不足。", True, True)
    await asyncio.sleep(0)
    send_image.assert_not_awaited()


@pytest.mark.asyncio
async def test_llm_delivery_keeps_text_when_structured_sticker_followup_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = MagicMock()
    send_text = AsyncMock(return_value=type("Receipt", (), {"delivered": True, "message_id": 1})())
    monkeypatch.setattr("pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt", send_text)
    send_image = AsyncMock(return_value=False)
    monkeypatch.setattr(delivery, "send_repeater_emotion_image", send_image)
    monkeypatch.setattr(
        delivery,
        "get_llm_config",
        lambda: MagicMock(
            llm_reply_postprocess_enabled=False,
            llm_reply_typo_enabled=False,
            llm_reply_typo_rate=0,
            llm_reply_trim_terminal_period_enabled=False,
            llm_reply_trim_terminal_period_rate=0,
            llm_reply_mention_cooldown_sec=0,
            llm_chat_sticker_enabled=True,
        ),
    )

    assert await delivery.deliver_llm_callback_success(
        "task-structured-no-image",
        {"task_type": LLM_CHAT_TASK_TYPE, "group_id": 222, "user_id": 333, "bot_id": 111, "user_text": "我想你"},
        bot=bot,
        group_id=222,
        bot_id=111,
        bot_id_str="111",
        text='{"reply":"我也在。","sticker":{"emotion":"开心","action":"挥手"}}',
        parsed_agent_trace=None,
        history_summary=None,
        history_keep_messages=None,
    ) == ("我也在。", True, True)
    send_text.assert_awaited_once()
    await asyncio.sleep(0)
    send_image.assert_awaited_once_with(bot, 222, 111, 333, "emotion:开心 action:挥手")


@pytest.mark.asyncio
async def test_llm_delivery_keeps_text_when_no_repeater_image_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = MagicMock()
    send_text = AsyncMock(return_value=type("Receipt", (), {"delivered": True, "message_id": 1})())
    monkeypatch.setattr(
        "pallas.core.platform.ai_callback.delivery.send_group_message_with_receipt",
        send_text,
    )
    monkeypatch.setattr(delivery, "send_repeater_emotion_image", AsyncMock(return_value=False))
    monkeypatch.setattr(
        delivery,
        "get_llm_config",
        lambda: MagicMock(
            llm_reply_postprocess_enabled=False,
            llm_reply_typo_enabled=False,
            llm_reply_typo_rate=0,
            llm_reply_trim_terminal_period_enabled=False,
            llm_reply_trim_terminal_period_rate=0,
            llm_reply_mention_cooldown_sec=0,
            llm_chat_sticker_enabled=True,
        ),
    )
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
async def test_repeater_image_sender_excludes_a_single_known_non_sticker(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater.model import Chat
    from pallas.product.llm.sticker_labels import StickerSemanticLabel, content_hash_for_bytes

    image = b"not-a-sticker"
    content_hash = content_hash_for_bytes(image)
    bot = MagicMock()
    bot.call_api = AsyncMock()
    monkeypatch.setattr(
        Chat,
        "find_reply_bundle",
        AsyncMock(return_value=SimpleNamespace(answer_list=["[CQ:image,file=photo]"], message_pool=[])),
    )
    monkeypatch.setattr("pallas.core.shared.utils.media_cache.get_image", AsyncMock(return_value=image))
    monkeypatch.setattr(
        "pallas.product.llm.sticker_label_jobs.sticker_label_repository",
        lambda: SimpleNamespace(
            get=AsyncMock(
                return_value=StickerSemanticLabel(content_hash=content_hash, is_sticker=False, confidence=0.99)
            )
        ),
    )
    enqueue_vision = AsyncMock()
    monkeypatch.setattr("pallas.product.llm.sticker_vision.enqueue_sticker_vision_job", enqueue_vision)
    monkeypatch.setattr(delivery, "get_llm_config", lambda: SimpleNamespace(llm_sticker_vision_enabled=True))

    assert not await delivery.send_repeater_emotion_image(bot, 222, 111, 333, "emotion:开心")
    enqueue_vision.assert_not_awaited()
    bot.call_api.assert_not_awaited()


@pytest.mark.asyncio
async def test_repeater_image_sender_uses_clear_label_leader_without_vision(monkeypatch: pytest.MonkeyPatch) -> None:
    from packages.repeater.model import Chat
    from pallas.product.llm.sticker_labels import StickerSemanticLabel, content_hash_for_bytes

    first = b"first-image"
    second = b"second-image"
    first_hash = content_hash_for_bytes(first)
    second_hash = content_hash_for_bytes(second)
    bot = MagicMock()
    bot.call_api = AsyncMock(return_value={"message_id": 1})
    monkeypatch.setattr(
        Chat,
        "find_reply_bundle",
        AsyncMock(
            return_value=SimpleNamespace(
                answer_list=["[CQ:image,file=first]", "[CQ:image,file=second]"], message_pool=[]
            )
        ),
    )
    monkeypatch.setattr(
        "pallas.core.shared.utils.media_cache.get_image",
        AsyncMock(side_effect=[first, second, second]),
    )
    repository = SimpleNamespace(
        get=AsyncMock(
            side_effect=lambda content_hash: {
                first_hash: StickerSemanticLabel(
                    content_hash=first_hash, is_sticker=True, emotions=("难过",), confidence=0.99
                ),
                second_hash: StickerSemanticLabel(
                    content_hash=second_hash, is_sticker=True, emotions=("开心",), confidence=0.99
                ),
            }.get(content_hash)
        )
    )
    monkeypatch.setattr("pallas.product.llm.sticker_label_jobs.sticker_label_repository", lambda: repository)
    enqueue_vision = AsyncMock()
    monkeypatch.setattr("pallas.product.llm.sticker_vision.enqueue_sticker_vision_job", enqueue_vision)
    monkeypatch.setattr(
        delivery,
        "get_llm_config",
        lambda: SimpleNamespace(
            llm_sticker_vision_enabled=True,
            llm_sticker_vision_timeout_sec=15,
            llm_sticker_vision_max_per_hour=12,
            llm_sticker_vision_candidate_count=4,
            llm_chat_sticker_cooldown_sec=0,
        ),
    )
    monkeypatch.setattr(
        "pallas.product.llm.sticker_followup.should_send_repeater_image",
        lambda *_args, **_kwargs: True,
    )

    assert await delivery.send_repeater_emotion_image(bot, 222, 111, 333, "emotion:开心")

    enqueue_vision.assert_not_awaited()
    sent = bot.call_api.await_args.kwargs["message"]
    assert str(sent[0].data["file"]).endswith("c2Vjb25kLWltYWdl")


@pytest.mark.asyncio
async def test_repeater_image_sender_enqueues_missing_labels_without_waiting_for_vision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.repeater.model import Chat

    bot = MagicMock()
    bot.call_api = AsyncMock()
    monkeypatch.setattr(
        Chat,
        "find_reply_bundle",
        AsyncMock(return_value=SimpleNamespace(answer_list=["[CQ:image,file=one]"], message_pool=[])),
    )
    monkeypatch.setattr("pallas.core.shared.utils.media_cache.get_image", AsyncMock(return_value=b"one-image"))
    monkeypatch.setattr(
        "pallas.product.llm.sticker_label_jobs.sticker_label_repository",
        lambda: SimpleNamespace(get=AsyncMock(return_value=None)),
    )
    enqueue_label = AsyncMock(return_value=True)
    monkeypatch.setattr("pallas.product.llm.sticker_label_jobs.enqueue_sticker_label_candidate", enqueue_label)
    enqueue_vision = AsyncMock()
    monkeypatch.setattr("pallas.product.llm.sticker_vision.enqueue_sticker_vision_job", enqueue_vision)
    monkeypatch.setattr(
        delivery,
        "get_llm_config",
        lambda: SimpleNamespace(
            llm_sticker_vision_enabled=True,
            llm_sticker_vision_timeout_sec=15,
            llm_sticker_vision_max_per_hour=12,
            llm_sticker_vision_candidate_count=4,
            llm_chat_sticker_cooldown_sec=0,
        ),
    )

    assert await delivery.send_repeater_emotion_image(bot, 222, 111, 333, "emotion:开心")

    enqueue_vision.assert_awaited_once()
    bot.call_api.assert_not_awaited()
    await asyncio.sleep(0)
    enqueue_label.assert_awaited_once()


@pytest.mark.asyncio
async def test_cached_sticker_sender_uses_cached_image_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    from pallas.core.shared.utils import media_cache

    bot = MagicMock()
    bot.call_api = AsyncMock(return_value={"message_id": 1})
    monkeypatch.setattr(media_cache, "get_latest_image", AsyncMock(return_value=b"cached-image"), raising=False)

    assert await delivery.send_cached_sticker_image(bot, 222)
    bot.call_api.assert_awaited_once()
