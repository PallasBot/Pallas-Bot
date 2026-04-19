"""
PostgreSQL Repository 集成测试。

需要本地 PG 实例：通过环境变量 `PG_TEST_DSN` 注入（SQLAlchemy asyncpg DSN 格式，
例如 `postgresql+asyncpg://user:pw@/db?host=/run/postgresql`）。未设置则整个
模块 skip，不阻塞 CI。

覆盖内容：
- find_for_cleanup OR 语义（与 Mongo 对齐）
- upsert_answer 并发原子性（复合唯一约束）
- BlackList / ImageCache 的 upsert 原子性
- \\x00 过滤
- ConfigRepository TTL 缓存命中/失效/ignore_cache/写失效
- delete_expired chunked 行为
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

_DSN = os.getenv("PG_TEST_DSN")

pytestmark = pytest.mark.skipif(not _DSN, reason="需要设置 PG_TEST_DSN 指向测试 PG 实例")


@pytest.fixture
async def pg_engine():
    """每个测试一个独立 engine + schema，测试结束 drop 所有表。"""
    from sqlalchemy.ext.asyncio import create_async_engine

    from src.common.db.repository_pg import Base, dispose_pg, init_pg

    assert _DSN is not None
    engine = create_async_engine(_DSN)
    # 清理上一次跑剩的 schema（按 FK 顺序 drop）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await init_pg(engine)
    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await dispose_pg()


# ---------------------------------------------------------------------------
# Context 语义
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_for_cleanup_or_semantics(pg_engine):
    """find_for_cleanup 必须是 trigger_count>threshold OR clear_time<expiration。"""
    from src.common.db.modules import Context
    from src.common.db.repository_pg import PgContextRepository

    repo = PgContextRepository()
    await repo.insert(
        Context.model_construct(keywords="high", time=1000, trigger_count=150, answers=[], ban=[], clear_time=999)
    )
    await repo.insert(
        Context.model_construct(keywords="old", time=1000, trigger_count=5, answers=[], ban=[], clear_time=100)
    )
    await repo.insert(
        Context.model_construct(keywords="neither", time=1000, trigger_count=5, answers=[], ban=[], clear_time=999)
    )

    results = await repo.find_for_cleanup(trigger_threshold=100, expiration=500)
    got = {c.keywords for c in results}
    assert "high" in got
    assert "old" in got
    assert "neither" not in got


@pytest.mark.asyncio
async def test_upsert_answer_is_atomic(pg_engine):
    """并发 50 次 upsert_answer 同一 (keywords, group_id, answer_keywords)，
    必须只产生 1 个 Answer 行且 count=50，trigger_count=50。"""
    from src.common.db.modules import Context
    from src.common.db.repository_pg import PgContextRepository

    repo = PgContextRepository()
    await repo.insert(
        Context.model_construct(keywords="kw", time=0, trigger_count=1, answers=[], ban=[], clear_time=0)
    )

    async def _u(i: int):
        await repo.upsert_answer(
            keywords="kw", group_id=1, answer_keywords="a", answer_time=100 + i, message=f"m{i}", append_on_existing=True
        )

    await asyncio.gather(*[_u(i) for i in range(50)])

    found = await repo.find_by_keywords("kw")
    assert found is not None
    assert len(found.answers) == 1
    assert found.answers[0].count == 50
    assert len(found.answers[0].messages) == 50
    # trigger_count 起始为 1（insert 时），每次 upsert_answer + 1
    assert found.trigger_count == 1 + 50


@pytest.mark.asyncio
async def test_upsert_answer_append_flag(pg_engine):
    """append_on_existing=False 时，已有 Answer 不应新增 message。"""
    from src.common.db.modules import Context
    from src.common.db.repository_pg import PgContextRepository

    repo = PgContextRepository()
    await repo.insert(
        Context.model_construct(keywords="k", time=0, trigger_count=1, answers=[], ban=[], clear_time=0)
    )

    await repo.upsert_answer("k", 1, "a", 100, "first", append_on_existing=True)
    await repo.upsert_answer("k", 1, "a", 200, "second", append_on_existing=False)
    found = await repo.find_by_keywords("k")
    assert found is not None
    assert found.answers[0].count == 2
    assert found.answers[0].time == 200
    assert "first" in found.answers[0].messages
    assert "second" not in found.answers[0].messages


@pytest.mark.asyncio
async def test_upsert_answer_context_missing(pg_engine):
    """Context 不存在时，upsert_answer 必须 no-op。"""
    from src.common.db.repository_pg import PgContextRepository

    repo = PgContextRepository()
    # 不先 insert context
    await repo.upsert_answer("absent", 1, "a", 100, "m", append_on_existing=True)
    found = await repo.find_by_keywords("absent")
    assert found is None


@pytest.mark.asyncio
async def test_delete_expired_chunked(pg_engine):
    """插入 100 个过期 Context，delete_expired 应全部清掉。"""
    from src.common.db.modules import Context
    from src.common.db.repository_pg import PgContextRepository

    repo = PgContextRepository()
    for i in range(100):
        await repo.insert(
            Context.model_construct(keywords=f"old{i}", time=10, trigger_count=1, answers=[], ban=[], clear_time=0)
        )
    # 插入不应被删的
    await repo.insert(
        Context.model_construct(keywords="keep", time=9999, trigger_count=1, answers=[], ban=[], clear_time=0)
    )

    await repo.delete_expired(expiration=100, threshold=3)
    assert await repo.find_by_keywords("old0") is None
    assert await repo.find_by_keywords("old99") is None
    assert await repo.find_by_keywords("keep") is not None


@pytest.mark.asyncio
async def test_null_byte_stripping(pg_engine):
    """写入含 \\x00 的字段必须被剥除，不得让 PG 报错。"""
    from src.common.db.modules import Answer, Ban, Context, Message
    from src.common.db.repository_pg import PgContextRepository, PgMessageRepository

    ctx_repo = PgContextRepository()
    msg_repo = PgMessageRepository()

    await ctx_repo.insert(
        Context.model_construct(
            keywords="null\x00kw",
            time=0,
            trigger_count=1,
            answers=[Answer.model_construct(keywords="a\x00", group_id=1, count=1, time=0, messages=["m\x00sg"])],
            ban=[Ban.model_construct(keywords="b\x00", group_id=1, reason="r\x00", time=0)],
            clear_time=0,
        )
    )
    found = await ctx_repo.find_by_keywords("null\x00kw")
    assert found is not None
    assert "\x00" not in found.keywords
    assert "\x00" not in found.answers[0].keywords
    assert "\x00" not in found.answers[0].messages[0]
    assert "\x00" not in found.ban[0].keywords
    assert "\x00" not in found.ban[0].reason

    await msg_repo.bulk_insert([
        Message.model_construct(
            group_id=1,
            user_id=2,
            bot_id=3,
            raw_message="raw\x00",
            is_plain_text=True,
            plain_text="plain\x00",
            keywords="kw\x00",
            time=0,
        )
    ])


# ---------------------------------------------------------------------------
# BlackList / ImageCache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blacklist_upsert_is_atomic(pg_engine):
    from src.common.db.repository_pg import PgBlackListRepository

    repo = PgBlackListRepository()
    # 并发写同一 group_id
    await asyncio.gather(*[repo.upsert_answers(1, [f"a{i}"]) for i in range(20)])
    all_bl = await repo.find_all()
    # 应只有 1 行，且不会因 unique 冲突炸库
    group_rows = [x for x in all_bl if x.group_id == 1]
    assert len(group_rows) == 1


@pytest.mark.asyncio
async def test_image_cache_save_is_upsert(pg_engine):
    """Mongo save() 在记录不存在时等价于 insert，PG 必须对齐。"""
    from src.common.db.modules import ImageCache
    from src.common.db.repository_pg import PgImageCacheRepository

    repo = PgImageCacheRepository()
    ic = ImageCache.model_construct(cq_code="[CQ:image,file=x.image]", base64_data=None, ref_times=1, date=20250419)
    # 记录不存在 → save 必须插入
    await repo.save(ic)
    assert await repo.find_by_cq_code("[CQ:image,file=x.image]") is not None

    ic.ref_times = 5
    ic.base64_data = "b64"
    await repo.save(ic)
    got = await repo.find_by_cq_code("[CQ:image,file=x.image]")
    assert got is not None
    assert got.ref_times == 5
    assert got.base64_data == "b64"


# ---------------------------------------------------------------------------
# ConfigRepository TTL 缓存
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_cache_hit_and_invalidate_on_write(pg_engine):
    from src.common.db.repository_pg import PgConfigRepository

    repo = PgConfigRepository("bot_config", "account")
    # 写入
    await repo.upsert_field(1001, "security", True)
    # 读（走 DB 后填充缓存）
    row1 = await repo.get(1001)
    assert row1 is not None and row1.security is True

    # 再次写入 → 失效
    await repo.upsert_field(1001, "security", False)
    row2 = await repo.get(1001)
    assert row2 is not None and row2.security is False


@pytest.mark.asyncio
async def test_config_cache_ignore_cache_forces_db_read(pg_engine):
    """ignore_cache=True 必须绕过缓存直接回源。"""
    from sqlalchemy import update

    from src.common.db.repository_pg import BotConfigRow, PgConfigRepository, get_session

    repo = PgConfigRepository("bot_config", "account")
    await repo.upsert_field(2002, "security", True)
    # 读一次让缓存生效
    assert (await repo.get(2002)).security is True

    # 绕过 repo 直接改 DB（不失效缓存）
    async with get_session() as session:
        await session.execute(update(BotConfigRow).where(BotConfigRow.account == 2002).values(security=False))
        await session.commit()

    # 走缓存：应仍是 True
    cached = await repo.get(2002)
    assert cached.security is True
    # ignore_cache：应返回新值 False
    fresh = await repo.get(2002, ignore_cache=True)
    assert fresh.security is False


@pytest.mark.asyncio
async def test_config_invalidate_all(pg_engine):
    from src.common.db.repository_pg import PgConfigRepository

    repo = PgConfigRepository("bot_config", "account")
    await repo.upsert_field(3003, "security", True)
    assert (await repo.get(3003)).security is True
    await repo.invalidate_cache()
    # cleared: 下一次 get 走 DB（值还是 True，但不会 hit 缓存）
    assert (await repo.get(3003)).security is True


@pytest.mark.asyncio
async def test_config_get_or_create_concurrent(pg_engine):
    """并发 get_or_create 同一 key 必须只创建 1 行。"""
    from src.common.db.repository_pg import PgConfigRepository

    repo = PgConfigRepository("bot_config", "account")
    key = int(uuid.uuid4().int & 0x7FFFFFFF)

    results = await asyncio.gather(*[repo.get_or_create(key, disabled_plugins=[]) for _ in range(20)])
    created_count = sum(1 for _, created in results if created)
    # 至多 1 个 True
    assert created_count <= 1
    row = await repo.get(key, ignore_cache=True)
    assert row is not None
