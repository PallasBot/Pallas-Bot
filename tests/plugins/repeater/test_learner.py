"""
Tests for Learner class.

Tests learning logic, context insertion, and filtering (repeat/reply skipping).
"""

import asyncio
from collections import defaultdict, deque
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_learn_db_fallback_when_memory_empty(beanie_fixture):
    """内存无近期链时不再回退 DB 群上下文，只保留 message_insert 主流程。"""
    from packages.repeater.learner import Learner
    from packages.repeater.message_store import MessageStore
    from packages.repeater.model import ChatData
    from pallas.core.foundation.db import Message as MessageModel

    MessageStore._message_lock = asyncio.Lock()
    MessageStore._message_dict = defaultdict(list)
    MessageStore._late_save_time = 0

    topics_lock = asyncio.Lock()
    recent_topics = defaultdict(lambda: deque(maxlen=10))

    try:
        group_id = 77701
        user_id = 67890
        bot_id = 11111
        prev_msg = MessageModel(
            group_id=group_id,
            user_id=99999,
            bot_id=bot_id,
            raw_message="db previous",
            is_plain_text=True,
            plain_text="db previous",
            keywords="db previous",
            time=1000,
        )
        chat_data = ChatData(
            group_id=group_id,
            user_id=user_id,
            raw_message="new from db path",
            plain_text="new from db path",
            time=2000,
            bot_id=bot_id,
        )

        async def fake_recent(gid: int, *, before_time=None, user_id=None, limit=8):
            if user_id is not None:
                return []
            assert gid == group_id
            assert before_time == 2000
            return [prev_msg]

        with (
            patch(
                "packages.repeater.message_store.message_repo.find_recent_in_group",
                new_callable=AsyncMock,
                side_effect=fake_recent,
            ),
            patch("packages.repeater.learner.context_repo.learn_answer", None, create=True),
            patch(
                "packages.repeater.learner.context_exists_for_learn",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "packages.repeater.learner.context_repo.context_exists_by_keywords",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch("packages.repeater.learner.context_repo.insert", new_callable=AsyncMock) as mock_insert,
        ):
            result = await Learner.learn(chat_data, topics_lock, recent_topics)

            assert result is True
            assert mock_insert.call_count == 0
    finally:
        MessageStore._message_dict.clear()
        MessageStore._late_save_time = 0


@pytest.mark.asyncio
async def test_learn_basic_flow(beanie_fixture):
    """
    Test that learn() inserts message and calls context_insert for previous message.
    """
    from packages.repeater.learner import Learner
    from packages.repeater.message_store import MessageStore
    from packages.repeater.model import ChatData
    from pallas.core.foundation.db import Message as MessageModel

    # Setup: Initialize MessageStore state
    MessageStore._message_lock = asyncio.Lock()
    MessageStore._message_dict = defaultdict(list)
    MessageStore._late_save_time = 0

    topics_lock = asyncio.Lock()
    recent_topics = defaultdict(lambda: deque(maxlen=10))

    try:
        group_id = 12345
        user_id = 67890
        bot_id = 11111

        # Pre-populate message_dict with a previous message
        prev_msg = MessageModel(
            group_id=group_id,
            user_id=99999,  # Different user
            bot_id=bot_id,
            raw_message="Previous message",
            is_plain_text=True,
            plain_text="Previous message",
            keywords="Previous message",
            time=1000,
        )
        MessageStore._message_dict[group_id].append(prev_msg)

        # Create new chat data
        chat_data = ChatData(
            group_id=group_id,
            user_id=user_id,
            raw_message="New message",
            plain_text="New message",
            time=2000,
            bot_id=bot_id,
        )

        with (
            patch("packages.repeater.learner.context_repo.learn_answer", None, create=True),
            patch(
                "packages.repeater.learner.context_exists_for_learn",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "packages.repeater.learner.context_repo.context_exists_by_keywords",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch("packages.repeater.learner.context_repo.insert", new_callable=AsyncMock) as mock_insert,
        ):
            result = await Learner.learn(chat_data, topics_lock, recent_topics)

            assert result is True
            assert mock_insert.call_count == 1

    finally:
        # Cleanup
        MessageStore._message_dict.clear()
        MessageStore._late_save_time = 0


@pytest.mark.asyncio
async def test_learn_skips_repeat_ignore_user_ids(beanie_fixture):
    """repeat_ignore / 本进程 Bot QQ 不参与学习：不插库、不写上下文。"""
    from packages.repeater.learner import Learner
    from packages.repeater.message_store import MessageStore
    from packages.repeater.model import ChatData
    from pallas.core.foundation.db import Message as MessageModel

    MessageStore._message_lock = asyncio.Lock()
    MessageStore._message_dict = defaultdict(list)
    MessageStore._late_save_time = 0

    topics_lock = asyncio.Lock()
    recent_topics = defaultdict(lambda: deque(maxlen=10))

    try:
        group_id = 55501
        ignored_uid = 888001
        bot_id = 11111

        prev_msg = MessageModel(
            group_id=group_id,
            user_id=99999,
            bot_id=bot_id,
            raw_message="before",
            is_plain_text=True,
            plain_text="before",
            keywords="before",
            time=1000,
        )
        MessageStore._message_dict[group_id].append(prev_msg)

        chat_data = ChatData(
            group_id=group_id,
            user_id=ignored_uid,
            raw_message="ignored user says",
            plain_text="ignored user says",
            time=2000,
            bot_id=bot_id,
        )

        with (
            patch(
                "packages.repeater.responder.Responder._repeat_ignore_user_ids",
                return_value={ignored_uid},
            ),
            patch(
                "packages.repeater.learner.context_repo.context_exists_by_keywords", new_callable=AsyncMock
            ) as mock_exists,
            patch("packages.repeater.learner.context_repo.insert", new_callable=AsyncMock) as mock_insert,
            patch(
                "packages.repeater.message_store.MessageStore.message_insert",
                new_callable=AsyncMock,
            ) as mock_insert_msg,
        ):
            result = await Learner.learn(chat_data, topics_lock, recent_topics)

            assert result is False
            mock_exists.assert_not_called()
            mock_insert.assert_not_called()
            mock_insert_msg.assert_not_called()
            assert len(MessageStore._message_dict[group_id]) == 1
    finally:
        MessageStore._message_dict.clear()
        MessageStore._late_save_time = 0


@pytest.mark.asyncio
async def test_learn_empty_message(beanie_fixture):
    """
    Test that learn() returns False for empty messages.
    """
    from packages.repeater.learner import Learner
    from packages.repeater.message_store import MessageStore
    from packages.repeater.model import ChatData

    MessageStore._message_lock = asyncio.Lock()
    MessageStore._message_dict = defaultdict(list)
    MessageStore._late_save_time = 0

    topics_lock = asyncio.Lock()
    recent_topics = defaultdict(lambda: deque(maxlen=10))

    try:
        chat_data = ChatData(
            group_id=12345,
            user_id=67890,
            raw_message="   ",  # Empty/whitespace only
            plain_text="",
            time=1000,
            bot_id=11111,
        )

        result = await Learner.learn(chat_data, topics_lock, recent_topics)

        # Should skip empty messages
        assert result is False

    finally:
        MessageStore._message_dict.clear()
        MessageStore._late_save_time = 0


@pytest.mark.asyncio
async def test_topics_callback_filters_niuniu_keywords(beanie_fixture):
    """
    Test that _topics_callback filters out keywords starting with '牛牛'
    before updating recent_topics.
    """
    from packages.repeater.learner import Learner
    from packages.repeater.message_store import MessageStore
    from packages.repeater.model import ChatData

    MessageStore._message_lock = asyncio.Lock()
    MessageStore._message_dict = defaultdict(list)
    MessageStore._late_save_time = 0

    topics_lock = asyncio.Lock()
    recent_topics = defaultdict(lambda: deque(maxlen=20))

    try:
        group_id = 12345
        bot_id = 11111

        # Build a plain-text message whose keywords include both normal and "牛牛..." tokens.
        # ChatData.keywords is a space-joined string; _keywords_list splits it back.
        chat_data = ChatData(
            group_id=group_id,
            user_id=67890,
            raw_message="你好 牛牛打架 世界 牛牛你好",
            plain_text="你好 牛牛打架 世界 牛牛你好",
            time=2000,
            bot_id=bot_id,
        )
        # Patch keywords so we control the exact token list
        chat_data._keywords_list = ["你好", "牛牛打架", "世界", "牛牛你好"]

        with (
            patch(
                "packages.repeater.learner.context_repo.context_exists_by_keywords",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch("packages.repeater.learner.context_repo.insert", new_callable=AsyncMock),
        ):
            result = await Learner.learn(chat_data, topics_lock, recent_topics)

        assert result is True

        topics = list(recent_topics[group_id])
        assert "你好" in topics, "Normal keyword '你好' should be in recent_topics"
        assert "世界" in topics, "Normal keyword '世界' should be in recent_topics"
        assert "牛牛打架" not in topics, "'牛牛打架' starts with '牛牛' and must be filtered out"
        assert "牛牛你好" not in topics, "'牛牛你好' starts with '牛牛' and must be filtered out"

    finally:
        MessageStore._message_dict.clear()
        MessageStore._late_save_time = 0


@pytest.mark.asyncio
async def test_context_insert_skip_repeat(beanie_fixture):
    """
    Test that _context_insert skips when message is a repeat.
    """
    from packages.repeater.learner import Learner
    from packages.repeater.model import ChatData
    from pallas.core.foundation.db import Message as MessageModel

    chat_data = ChatData(
        group_id=12345,
        user_id=67890,
        raw_message="Same message",
        plain_text="Same message",
        time=2000,
        bot_id=11111,
    )

    # Previous message is identical (repeat)
    pre_msg = MessageModel(
        group_id=12345,
        user_id=99999,
        bot_id=11111,
        raw_message="Same message",  # Same as current
        is_plain_text=True,
        plain_text="Same message",
        keywords="Same message",
        time=1000,
    )

    with patch("packages.repeater.learner.context_repo.context_exists_by_keywords") as mock_exists:
        # Call context_insert
        await Learner._context_insert(chat_data, pre_msg)

        assert mock_exists.call_count == 0, "Should skip repeats without querying Context"


@pytest.mark.asyncio
async def test_context_insert_skip_reply(beanie_fixture):
    """
    Test that _context_insert skips when message is a reply.
    """
    from packages.repeater.learner import Learner
    from packages.repeater.model import ChatData
    from pallas.core.foundation.db import Message as MessageModel

    # Message contains [CQ:reply, tag
    chat_data = ChatData(
        group_id=12345,
        user_id=67890,
        raw_message="[CQ:reply,id=123]Reply message",
        plain_text="Reply message",
        time=2000,
        bot_id=11111,
    )

    pre_msg = MessageModel(
        group_id=12345,
        user_id=99999,
        bot_id=11111,
        raw_message="Original message",
        is_plain_text=True,
        plain_text="Original message",
        keywords="Original message",
        time=1000,
    )

    with patch("packages.repeater.learner.context_repo.context_exists_by_keywords") as mock_exists:
        # Call context_insert
        await Learner._context_insert(chat_data, pre_msg)

        assert mock_exists.call_count == 0, "Should skip replies without querying Context"


@pytest.mark.asyncio
async def test_context_insert_skip_none(beanie_fixture):
    """
    Test that _context_insert skips when pre_msg is None.
    """
    from packages.repeater.learner import Learner
    from packages.repeater.model import ChatData

    chat_data = ChatData(
        group_id=12345,
        user_id=67890,
        raw_message="New message",
        plain_text="New message",
        time=2000,
        bot_id=11111,
    )

    with patch("packages.repeater.learner.context_repo.context_exists_by_keywords") as mock_exists:
        # Call context_insert with None
        await Learner._context_insert(chat_data, None)

        assert mock_exists.call_count == 0, "Should skip None pre_msg without querying Context"


@pytest.mark.asyncio
async def test_context_insert_calls_upsert_answer_when_context_exists(beanie_fixture):
    """
    Context 已存在时，_context_insert 应委托 upsert_answer，
    以便在拆表后具备原子 inc count 的能力。
    """
    from packages.repeater.learner import Learner
    from packages.repeater.model import ChatData
    from pallas.core.foundation.db import Message as MessageModel

    chat_data = ChatData(
        group_id=12345,
        user_id=67890,
        raw_message="Response message",
        plain_text="Response message",
        time=2000,
        bot_id=11111,
    )

    pre_msg = MessageModel(
        group_id=12345,
        user_id=99999,
        bot_id=11111,
        raw_message="Trigger message",
        is_plain_text=True,
        plain_text="Trigger message",
        keywords="Trigger message",
        time=1000,
    )

    with (
        patch("packages.repeater.learner.context_repo.learn_answer", None, create=True),
        patch(
            "packages.repeater.learner.context_exists_for_learn",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("packages.repeater.learner.context_repo.upsert_answer", new_callable=AsyncMock) as mock_upsert,
        patch("packages.repeater.learner.context_repo.insert", new_callable=AsyncMock) as mock_insert,
        patch("packages.repeater.learner.context_repo.save", new_callable=AsyncMock) as mock_save,
    ):
        await Learner._context_insert(chat_data, pre_msg)

        assert mock_upsert.call_count == 1
        call_kwargs = mock_upsert.call_args.kwargs
        assert call_kwargs["keywords"] == pre_msg.keywords
        assert call_kwargs["group_id"] == chat_data.group_id
        assert call_kwargs["answer_keywords"] == chat_data.keywords
        assert call_kwargs["answer_time"] == chat_data.time
        assert call_kwargs["message"] == chat_data.raw_message
        assert call_kwargs["append_on_existing"] is True  # plain text

        assert mock_insert.call_count == 0
        assert mock_save.call_count == 0


@pytest.mark.asyncio
async def test_context_insert_prefers_repo_learn_answer_fast_path(beanie_fixture):
    """
    若仓储提供 learn_answer 快路径，_context_insert 应直接走单次写入，
    不再先做 context_exists_for_learn 的额外查库。
    """
    from packages.repeater.learner import Learner
    from packages.repeater.model import ChatData
    from pallas.core.foundation.db import Message as MessageModel

    chat_data = ChatData(
        group_id=12345,
        user_id=67890,
        raw_message="Response message",
        plain_text="Response message",
        time=2000,
        bot_id=11111,
    )

    pre_msg = MessageModel(
        group_id=12345,
        user_id=99999,
        bot_id=11111,
        raw_message="Trigger message",
        is_plain_text=True,
        plain_text="Trigger message",
        keywords="Trigger message",
        time=1000,
    )

    with (
        patch(
            "packages.repeater.learner.context_repo.learn_answer",
            new_callable=AsyncMock,
            return_value=True,
            create=True,
        ) as mock_learn_answer,
        patch(
            "packages.repeater.learner.context_exists_for_learn",
            new_callable=AsyncMock,
        ) as mock_exists,
        patch("packages.repeater.learner.context_repo.insert", new_callable=AsyncMock) as mock_insert,
        patch("packages.repeater.learner.context_repo.upsert_answer", new_callable=AsyncMock) as mock_upsert,
    ):
        await Learner._context_insert(chat_data, pre_msg)

        mock_learn_answer.assert_awaited_once()
        mock_exists.assert_not_called()
        mock_insert.assert_not_called()
        mock_upsert.assert_not_called()


@pytest.mark.asyncio
async def test_context_insert_no_append_when_non_plain_text(beanie_fixture):
    """
    非纯文本消息对已有 answer 不应 push message，
    通过 upsert_answer 的 append_on_existing=False 表达。
    """
    from packages.repeater.learner import Learner
    from packages.repeater.model import ChatData
    from pallas.core.foundation.db import Message as MessageModel

    # 含 CQ 码 => is_plain_text=False
    chat_data = ChatData(
        group_id=12345,
        user_id=67890,
        raw_message="[CQ:image,url=x]",
        plain_text="",
        time=2000,
        bot_id=11111,
    )
    assert not chat_data.is_plain_text

    pre_msg = MessageModel(
        group_id=12345,
        user_id=99999,
        bot_id=11111,
        raw_message="Trigger",
        is_plain_text=True,
        plain_text="Trigger",
        keywords="Trigger",
        time=1000,
    )

    with (
        patch("packages.repeater.learner.context_repo.learn_answer", None, create=True),
        patch(
            "packages.repeater.learner.context_exists_for_learn",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch("packages.repeater.learner.context_repo.upsert_answer", new_callable=AsyncMock) as mock_upsert,
    ):
        await Learner._context_insert(chat_data, pre_msg)

        assert mock_upsert.call_args.kwargs["append_on_existing"] is False


@pytest.mark.asyncio
async def test_context_insert_creates_new_context_when_missing(beanie_fixture):
    """
    Context 不存在时应走 insert(Context(...)) 路径，不调用 upsert_answer。
    """
    from packages.repeater.learner import Learner
    from packages.repeater.model import ChatData
    from pallas.core.foundation.db import Message as MessageModel

    chat_data = ChatData(
        group_id=12345,
        user_id=67890,
        raw_message="New response",
        plain_text="New response",
        time=2000,
        bot_id=11111,
    )
    pre_msg = MessageModel(
        group_id=12345,
        user_id=99999,
        bot_id=11111,
        raw_message="Trigger",
        is_plain_text=True,
        plain_text="Trigger",
        keywords="Trigger",
        time=1000,
    )

    with (
        patch("packages.repeater.learner.context_repo.learn_answer", None, create=True),
        patch(
            "packages.repeater.learner.context_exists_for_learn",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch("packages.repeater.learner.context_repo.insert", new_callable=AsyncMock) as mock_insert,
        patch("packages.repeater.learner.context_repo.upsert_answer", new_callable=AsyncMock) as mock_upsert,
    ):
        await Learner._context_insert(chat_data, pre_msg)

        assert mock_insert.call_count == 1
        assert mock_upsert.call_count == 0
        inserted_ctx = mock_insert.call_args.args[0]
        assert inserted_ctx.keywords == pre_msg.keywords
        assert len(inserted_ctx.answers) == 1
        assert inserted_ctx.answers[0].keywords == chat_data.keywords


@pytest.mark.asyncio
async def test_learn_user_backtracking(beanie_fixture):
    """
    Test that learn() finds user's previous message within last 3 messages.
    """
    from packages.repeater.learner import Learner
    from packages.repeater.message_store import MessageStore
    from packages.repeater.model import ChatData
    from pallas.core.foundation.db import Message as MessageModel

    MessageStore._message_lock = asyncio.Lock()
    MessageStore._message_dict = defaultdict(list)
    MessageStore._late_save_time = 0

    topics_lock = asyncio.Lock()
    recent_topics = defaultdict(lambda: deque(maxlen=10))

    try:
        group_id = 12345
        user_id = 67890
        bot_id = 11111

        # Pre-populate with messages where user's previous is within last 3
        MessageStore._message_dict[group_id].append(
            MessageModel(
                group_id=group_id,
                user_id=99990,  # Different user (oldest)
                bot_id=bot_id,
                raw_message="Very old message",
                is_plain_text=True,
                plain_text="Very old message",
                keywords="Very old message",
                time=900,
            )
        )
        MessageStore._message_dict[group_id].append(
            MessageModel(
                group_id=group_id,
                user_id=99991,
                bot_id=bot_id,
                raw_message="Other user 1",
                is_plain_text=True,
                plain_text="Other user 1",
                keywords="Other user 1",
                time=1100,
            )
        )
        MessageStore._message_dict[group_id].append(
            MessageModel(
                group_id=group_id,
                user_id=user_id,  # Same user - within backtracking range
                bot_id=bot_id,
                raw_message="User old message",
                is_plain_text=True,
                plain_text="User old message",
                keywords="User old message",
                time=1150,
            )
        )
        MessageStore._message_dict[group_id].append(
            MessageModel(
                group_id=group_id,
                user_id=99992,
                bot_id=bot_id,
                raw_message="Other user 2",
                is_plain_text=True,
                plain_text="Other user 2",
                keywords="Other user 2",
                time=1200,
            )
        )

        # Current message from same user
        chat_data = ChatData(
            group_id=group_id,
            user_id=user_id,
            raw_message="User new message",
            plain_text="User new message",
            time=2000,
            bot_id=bot_id,
        )

        with (
            patch("packages.repeater.learner.context_repo.learn_answer", None, create=True),
            patch(
                "packages.repeater.learner.context_exists_for_learn",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "packages.repeater.learner.context_repo.context_exists_by_keywords",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch("packages.repeater.learner.context_repo.insert", new_callable=AsyncMock) as mock_insert,
        ):
            result = await Learner.learn(chat_data, topics_lock, recent_topics)

            assert result is True
            assert mock_insert.call_count == 1, "Should only learn from the immediately previous group message"

    finally:
        MessageStore._message_dict.clear()
        MessageStore._late_save_time = 0
