from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pallas.core.foundation.db import Message
from pallas.product.llm import group_timeline
from pallas.product.llm.group_timeline import (
    GroupTimelineImage,
    format_group_timeline,
    format_group_timeline_context,
    should_include_group_timeline,
)


def test_format_group_timeline_keeps_speakers_order_and_reply_target() -> None:
    timeline = format_group_timeline([
        Message.model_construct(
            group_id=1,
            user_id=11,
            bot_id=99,
            plain_text="还是笨蛋欸",
            sender_name="兔兔",
            message_id=101,
            time=1,
        ),
        Message.model_construct(
            group_id=1,
            user_id=22,
            bot_id=99,
            plain_text="@牛牛",
            sender_name="醉湖",
            message_id=102,
            reply_to_message_id=101,
            time=2,
        ),
    ])

    assert timeline == "【刚才的群聊】\n- 兔兔：还是笨蛋欸\n- 醉湖（回兔兔的话）：@牛牛"


def test_format_group_timeline_uses_stable_label_for_legacy_messages() -> None:
    timeline = format_group_timeline([
        Message.model_construct(
            group_id=1,
            user_id=11,
            bot_id=99,
            plain_text="还在吗",
            time=1,
        )
    ])

    assert timeline == "【刚才的群聊】\n- 群友#0011：还在吗"


def test_format_group_timeline_skips_reply_id_when_target_absent() -> None:
    timeline = format_group_timeline([
        Message.model_construct(
            group_id=1,
            user_id=22,
            bot_id=99,
            plain_text="@牛牛",
            sender_name="醉湖",
            message_id=102,
            reply_to_message_id=999,
            time=2,
        )
    ])

    assert timeline == "【刚才的群聊】\n- 醉湖：@牛牛"


@pytest.mark.asyncio
async def test_build_recent_group_timeline_excludes_current_message(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = SimpleNamespace(
        find_recent_in_group=AsyncMock(
            return_value=[
                Message.model_construct(
                    group_id=1,
                    user_id=11,
                    bot_id=99,
                    plain_text="兔兔刚说的",
                    sender_name="兔兔",
                    message_id=101,
                    time=1,
                ),
                Message.model_construct(
                    group_id=1,
                    user_id=22,
                    bot_id=99,
                    plain_text="@牛牛",
                    sender_name="醉湖",
                    message_id=102,
                    time=2,
                ),
            ]
        )
    )
    monkeypatch.setattr(group_timeline, "make_message_repository", lambda: repo)

    timeline = await group_timeline.build_recent_group_timeline(1, current_message_id=102)

    assert "兔兔刚说的" in timeline
    assert "醉湖：@牛牛" not in timeline
    repo.find_recent_in_group.assert_awaited_once_with(1, limit=9)


def test_format_group_timeline_labels_own_and_peer_bot_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pallas.product.llm import sender_identity

    monkeypatch.setattr(sender_identity, "peer_bot_ids", lambda: frozenset({77}))
    sender_identity.clear_sender_identity_cache()

    timeline = format_group_timeline(
        [
            Message.model_construct(
                group_id=1,
                user_id=99,
                bot_id=99,
                plain_text="我自己说的",
                sender_name="牛牛",
                message_id=101,
                time=1,
            ),
            Message.model_construct(
                group_id=1,
                user_id=77,
                bot_id=99,
                plain_text="别的牛说的",
                sender_name="阿灿",
                message_id=102,
                time=2,
            ),
            Message.model_construct(
                group_id=1,
                user_id=11,
                bot_id=99,
                plain_text="真人说的",
                sender_name="阿灿",
                message_id=103,
                time=3,
            ),
        ],
        self_bot_id=99,
    )

    assert "- 牛牛：我自己说的" in timeline
    assert "- 别的牛：别的牛说的" in timeline
    assert "- 阿灿：真人说的" in timeline


def test_format_group_timeline_context_extracts_raw_images_and_keeps_placeholder() -> None:
    context = format_group_timeline_context([
        Message.model_construct(
            group_id=1,
            user_id=11,
            bot_id=99,
            raw_message="[CQ:image,file=photo,url=https://example.com/a.png] 看这个",
            plain_text="看这个",
            sender_name="兔兔",
            message_id=101,
            time=1,
        ),
    ])

    assert context.text == "【刚才的群聊】\n- 兔兔：[图片] 看这个"
    assert context.images == (
        GroupTimelineImage(speaker="兔兔", text="看这个", url="https://example.com/a.png"),
    )


def test_format_group_timeline_context_extracts_raw_mface_image() -> None:
    context = format_group_timeline_context([
        Message.model_construct(
            group_id=1,
            user_id=11,
            bot_id=99,
            raw_message="[CQ:mface,emoji_id=128077,url=https://example.com/mface.png]",
            plain_text="",
            sender_name="兔兔",
            message_id=101,
            time=1,
        ),
    ])

    assert context.text == "【刚才的群聊】\n- 兔兔：[图片]"
    assert context.images == (
        GroupTimelineImage(speaker="兔兔", text="", url="https://example.com/mface.png"),
    )


def test_should_include_group_timeline_for_vision_turn() -> None:
    assert should_include_group_timeline(is_to_me=False, speak_trigger="vision") is True


def test_format_group_timeline_context_keeps_image_without_url_as_text_placeholder() -> None:
    context = format_group_timeline_context([
        Message.model_construct(
            group_id=1,
            user_id=11,
            bot_id=99,
            raw_message="[CQ:image,file=photo]",
            plain_text="",
            sender_name="兔兔",
            message_id=101,
            time=1,
        ),
    ])

    assert context.text == "【刚才的群聊】\n- 兔兔：[图片]"
    assert context.images == ()


def test_format_group_timeline_context_deduplicates_urls_and_caps_history_images() -> None:
    messages = [
        Message.model_construct(
            group_id=1,
            user_id=index,
            bot_id=99,
            raw_message=f"[CQ:image,url={url}] 图片{index}",
            plain_text=f"图片{index}",
            sender_name=f"用户{index}",
            message_id=index,
            time=index,
        )
        for index, url in enumerate(
            [
                "https://example.com/a.png",
                "HTTPS://EXAMPLE.COM/A.PNG",
                "https://example.com/b.png",
                "https://example.com/c.png",
                "https://example.com/d.png",
            ],
            start=1,
        )
    ]

    context = format_group_timeline_context(messages)

    assert [item.url for item in context.images] == [
        "https://example.com/a.png",
        "https://example.com/b.png",
        "https://example.com/c.png",
    ]
