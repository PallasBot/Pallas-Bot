"""Integration tests for MongoDB Repository implementations."""

import time

import pytest

from src.common.db.modules import Answer, Ban, Context, Message
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
async def test_upsert_answer_increments_existing(beanie_fixture):
    """已存在的 answer 应原子 inc count 并更新 time；append_on_existing=True 时 push message。"""
    repo = MongoContextRepository()
    cur = int(time.time())
    await repo.insert(
        Context(
            keywords="kw",
            time=cur,
            trigger_count=1,  # type: ignore
            answers=[Answer(keywords="a", group_id=1, count=3, time=cur, messages=["m0"])],
        )
    )

    await repo.upsert_answer(
        "kw", group_id=1, answer_keywords="a", answer_time=cur + 10, message="m1", append_on_existing=True
    )

    found = await repo.find_by_keywords("kw")
    assert found is not None
    assert len(found.answers) == 1
    assert found.answers[0].count == 4
    assert found.answers[0].time == cur + 10
    assert found.answers[0].messages == ["m0", "m1"]
    assert found.trigger_count == 2
    assert found.time == cur + 10


@pytest.mark.asyncio
async def test_upsert_answer_no_append_when_flag_false(beanie_fixture):
    """append_on_existing=False 时不应把 message push 到 existing answer.messages。"""
    repo = MongoContextRepository()
    cur = int(time.time())
    await repo.insert(
        Context(
            keywords="kw",
            time=cur,
            trigger_count=1,  # type: ignore
            answers=[Answer(keywords="a", group_id=1, count=1, time=cur, messages=["m0"])],
        )
    )

    await repo.upsert_answer("kw", 1, "a", cur + 10, message="m1", append_on_existing=False)

    found = await repo.find_by_keywords("kw")
    assert found is not None
    assert found.answers[0].count == 2
    assert found.answers[0].messages == ["m0"]


@pytest.mark.asyncio
async def test_upsert_answer_creates_new_when_not_exist(beanie_fixture):
    """不存在的 answer 应被创建，messages=[message]。"""
    repo = MongoContextRepository()
    cur = int(time.time())
    await repo.insert(Context(keywords="kw", time=cur, trigger_count=1, answers=[]))  # type: ignore

    await repo.upsert_answer("kw", 1, "a", cur + 10, message="hello", append_on_existing=True)

    found = await repo.find_by_keywords("kw")
    assert found is not None
    assert len(found.answers) == 1
    assert found.answers[0].keywords == "a"
    assert found.answers[0].group_id == 1
    assert found.answers[0].count == 1
    assert found.answers[0].time == cur + 10
    assert found.answers[0].messages == ["hello"]
    assert found.trigger_count == 2


@pytest.mark.asyncio
async def test_upsert_answer_differentiates_by_group(beanie_fixture):
    """相同 answer_keywords 但不同 group_id 应被视为不同 answer。"""
    repo = MongoContextRepository()
    cur = int(time.time())
    await repo.insert(
        Context(
            keywords="kw",
            time=cur,
            trigger_count=1,  # type: ignore
            answers=[Answer(keywords="a", group_id=1, count=1, time=cur, messages=["m0"])],
        )
    )

    await repo.upsert_answer(
        "kw", group_id=2, answer_keywords="a", answer_time=cur + 5, message="m2", append_on_existing=True
    )

    found = await repo.find_by_keywords("kw")
    assert found is not None
    assert len(found.answers) == 2


@pytest.mark.asyncio
async def test_upsert_answer_sequential_count_accuracy(beanie_fixture):
    """多次顺序 upsert_answer 应精确累加 count（验证 $inc 语义，避免读-改-写丢更新）。"""
    repo = MongoContextRepository()
    cur = int(time.time())
    await repo.insert(Context(keywords="kw", time=cur, trigger_count=1, answers=[]))  # type: ignore

    for i in range(10):
        await repo.upsert_answer("kw", 1, "a", cur + i, f"m{i}", append_on_existing=True)

    found = await repo.find_by_keywords("kw")
    assert found is not None
    assert len(found.answers) == 1
    assert found.answers[0].count == 10
    assert len(found.answers[0].messages) == 10  # 9 次追加 + 初始 1 条
    assert found.trigger_count == 11  # 初始 1 + 10 次递增


@pytest.mark.asyncio
async def test_upsert_answer_concurrent_atomicity(beanie_fixture):
    """
    并发 upsert_answer 到同一 (keywords, answer_keywords) 时，count 不应因为
    读-改-写丢更新。$inc 语义下 N 次并发调用 count 必然等于 N（第一次 +1 新建，
    后续 N-1 次 +1 累加）。
    """
    import asyncio as _asyncio

    repo = MongoContextRepository()
    cur = int(time.time())
    await repo.insert(Context(keywords="kw", time=cur, trigger_count=0, answers=[]))  # type: ignore

    async def call(i: int) -> None:
        await repo.upsert_answer("kw", 1, "a", cur + i, f"m{i}", append_on_existing=True)

    # mongomock 不是真并发，但 asyncio.gather 至少能暴露 await 点之间的交错丢更新
    await _asyncio.gather(*(call(i) for i in range(20)))

    found = await repo.find_by_keywords("kw")
    assert found is not None
    assert len(found.answers) == 1, "并发 upsert 不应产生重复 answer"
    assert found.answers[0].count == 20
    assert found.trigger_count == 20


@pytest.mark.asyncio
async def test_replace_answers(beanie_fixture):
    """replace_answers 应整体替换 answers 列表并更新 clear_time。"""
    repo = MongoContextRepository()
    cur = int(time.time())
    await repo.insert(
        Context(
            keywords="kw",
            time=cur,
            trigger_count=5,  # type: ignore
            answers=[
                Answer(keywords="a1", group_id=1, count=1, time=cur, messages=["m1"]),
                Answer(keywords="a2", group_id=1, count=1, time=cur, messages=["m2"]),
            ],
        )
    )

    new_answers = [Answer(keywords="a2", group_id=1, count=5, time=cur + 100, messages=["m2"])]
    await repo.replace_answers("kw", new_answers, clear_time=cur + 200)

    found = await repo.find_by_keywords("kw")
    assert found is not None
    assert len(found.answers) == 1
    assert found.answers[0].keywords == "a2"
    assert found.answers[0].count == 5
    assert found.clear_time == cur + 200
    # trigger_count 不应被 replace_answers 改动
    assert found.trigger_count == 5


@pytest.mark.asyncio
async def test_append_ban(beanie_fixture):
    """append_ban 应把 Ban 追加到 context.ban 列表。"""
    repo = MongoContextRepository()
    cur = int(time.time())
    await repo.insert(Context(keywords="kw", time=cur, trigger_count=1, answers=[]))  # type: ignore

    ban = Ban(keywords="bad", group_id=1, reason="test", time=cur)
    await repo.append_ban("kw", ban)

    found = await repo.find_by_keywords("kw")
    assert found is not None
    assert len(found.ban) == 1
    assert found.ban[0].keywords == "bad"
    assert found.ban[0].group_id == 1
    assert found.ban[0].reason == "test"


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
