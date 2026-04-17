"""Integration tests for MongoDB Repository implementations."""

import time

import pytest

from src.common.db.modules import Answer, Context, Message
from src.common.db.repository import (
    BlackListRepository,
    ContextRepository,
    MessageRepository,
)
from src.common.db.repository_impl import (
    MongoBlackListRepository,
    MongoContextRepository,
    MongoMessageRepository,
)


def test_mongo_context_satisfies_protocol():
    repo = MongoContextRepository()
    assert isinstance(repo, ContextRepository)


def test_mongo_message_satisfies_protocol():
    repo = MongoMessageRepository()
    assert isinstance(repo, MessageRepository)


def test_mongo_blacklist_satisfies_protocol():
    repo = MongoBlackListRepository()
    assert isinstance(repo, BlackListRepository)


@pytest.mark.asyncio
async def test_context_repo_crud(beanie_fixture):
    """Test Context CRUD operations: insert, find_by_keywords, save."""
    repo = MongoContextRepository()

    # Insert a new context
    ctx = Context(
        keywords="test_keyword",
        time=int(time.time()),
        trigger_count=1,  # type: ignore
        answers=[Answer(keywords="reply_kw", group_id=123, count=1, time=int(time.time()), messages=["hello"])],
    )
    await repo.insert(ctx)

    # Find by keywords
    found = await repo.find_by_keywords("test_keyword")
    assert found is not None
    assert found.keywords == "test_keyword"
    assert len(found.answers) == 1

    # Update and save
    found.trigger_count += 1
    await repo.save(found)

    found_again = await repo.find_by_keywords("test_keyword")
    assert found_again is not None
    assert found_again.trigger_count == 2


@pytest.mark.asyncio
async def test_context_repo_find_not_found(beanie_fixture):
    """Test find_by_keywords returns None for non-existent keywords."""
    repo = MongoContextRepository()
    result = await repo.find_by_keywords("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_context_repo_delete_expired(beanie_fixture):
    """Test delete_expired removes old low-count contexts."""
    repo = MongoContextRepository()

    old_time = 1000
    new_time = int(time.time())

    # Insert old context with low trigger_count
    old_ctx = Context(keywords="old_kw", time=old_time, trigger_count=1, answers=[])  # type: ignore
    await repo.insert(old_ctx)

    # Insert new context
    new_ctx = Context(keywords="new_kw", time=new_time, trigger_count=5, answers=[])  # type: ignore
    await repo.insert(new_ctx)

    # Delete expired (threshold=3 means contexts with trigger_count < 3 and time < expiration)
    await repo.delete_expired(expiration=new_time - 100, threshold=3)

    # Old context should be deleted
    assert await repo.find_by_keywords("old_kw") is None
    # New context should remain
    assert await repo.find_by_keywords("new_kw") is not None


@pytest.mark.asyncio
async def test_context_repo_find_for_cleanup(beanie_fixture):
    """Test find_for_cleanup finds contexts needing cleanup."""
    repo = MongoContextRepository()
    cur_time = int(time.time())

    # Insert context with high trigger_count
    ctx = Context(keywords="popular", time=cur_time, trigger_count=200, clear_time=cur_time, answers=[])  # type: ignore
    await repo.insert(ctx)

    results = await repo.find_for_cleanup(trigger_threshold=100, expiration=cur_time - 100)
    assert len(results) >= 1
    assert any(c.keywords == "popular" for c in results)


@pytest.mark.asyncio
async def test_message_repo_bulk_insert(beanie_fixture):
    """Test bulk_insert writes all messages."""
    repo = MongoMessageRepository()

    messages = [
        Message(
            group_id=123,
            user_id=456,
            bot_id=789,
            raw_message=f"msg_{i}",
            is_plain_text=True,
            plain_text=f"msg_{i}",
            keywords=f"kw_{i}",
            time=int(time.time()) + i,
        )
        for i in range(10)
    ]

    await repo.bulk_insert(messages)

    # Verify all messages were inserted
    all_msgs = await Message.find_all().to_list()
    assert len(all_msgs) == 10


@pytest.mark.asyncio
async def test_blacklist_repo_crud(beanie_fixture):
    """Test BlackList upsert and find_all."""
    repo = MongoBlackListRepository()

    # Initial upsert creates new record
    await repo.upsert_answers(group_id=111, answers=["bad_word_1"])

    all_bl = await repo.find_all()
    assert len(all_bl) == 1
    assert all_bl[0].group_id == 111
    assert "bad_word_1" in all_bl[0].answers

    # Second upsert updates existing record
    await repo.upsert_answers(group_id=111, answers=["bad_word_1", "bad_word_2"])

    all_bl = await repo.find_all()
    assert len(all_bl) == 1
    assert len(all_bl[0].answers) == 2

    # Upsert answers_reserve
    await repo.upsert_answers_reserve(group_id=111, answers=["reserve_1"])

    all_bl = await repo.find_all()
    assert len(all_bl) == 1
    assert "reserve_1" in all_bl[0].answers_reserve
