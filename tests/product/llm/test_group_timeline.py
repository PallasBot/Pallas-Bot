from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pallas.core.foundation.db import Message
from pallas.product.llm import group_timeline
from pallas.product.llm.group_timeline import format_group_timeline


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
