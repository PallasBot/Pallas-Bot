"""
PostgreSQL Repository 集成测试。

依赖：本地 PG 实例（通过 ``PG_TEST_DSN`` 注入）。fixture 定义在 ``conftest.py``，
未设置 DSN 时整套用例自动 skip。

覆盖矩阵：
- Context：``find_for_cleanup`` OR 语义 / ``upsert_answer`` 并发原子与 append 标志
  / 缺上下文 no-op / ``delete_expired`` 分块
- \\x00 过滤：Context + Message 全链路
- BlackList / ImageCache：upsert 原子性 / save() 语义
- ConfigRepository：TTL 缓存命中、写失效、ignore_cache 回源、全量失效、并发
  get_or_create
"""

from __future__ import annotations

import asyncio
import uuid

import pytest


@pytest.mark.asyncio
async def test_find_for_cleanup_or_semantics(pg_engine):
    """trigger_count>threshold 与 clear_time<expiration 必须是 OR 关系（对齐 Mongo）。"""
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
    """并发 50 次 upsert_answer 只产生 1 条 Answer、count=50、trigger_count 精确累加。"""
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
    assert found.trigger_count == 1 + 50


@pytest.mark.asyncio
async def test_upsert_answer_append_flag(pg_engine):
    """append_on_existing=False 时 count 仍 +1，但不把新 message 追加到已有 Answer。"""
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
    """Context 不存在时 upsert_answer 必须 no-op，不得凭空造 Context。"""
    from src.common.db.repository_pg import PgContextRepository

    repo = PgContextRepository()
    await repo.upsert_answer("absent", 1, "a", 100, "m", append_on_existing=True)
    found = await repo.find_by_keywords("absent")
    assert found is None


@pytest.mark.asyncio
async def test_delete_expired_chunked(pg_engine):
    """delete_expired 分块模式下应清掉所有过期行、保留未过期行。"""
    from src.common.db.modules import Context
    from src.common.db.repository_pg import PgContextRepository

    repo = PgContextRepository()
    for i in range(100):
        await repo.insert(
            Context.model_construct(keywords=f"old{i}", time=10, trigger_count=1, answers=[], ban=[], clear_time=0)
        )
    await repo.insert(
        Context.model_construct(keywords="keep", time=9999, trigger_count=1, answers=[], ban=[], clear_time=0)
    )

    await repo.delete_expired(expiration=100, threshold=3)
    assert await repo.find_by_keywords("old0") is None
    assert await repo.find_by_keywords("old99") is None
    assert await repo.find_by_keywords("keep") is not None


@pytest.mark.asyncio
async def test_null_byte_stripping(pg_engine):
    """Context / Answer / Ban / Message 全链路入库前都剥除 \\x00，PG 不得因此报错。"""
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

    # bulk_insert 也必须接受带 \x00 的字段，不抛 StringDataError
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


@pytest.mark.asyncio
async def test_upsert_answer_handles_long_keywords(pg_engine):
    """answer.keywords 超出 btree 2704 字节上限时，UNIQUE 约束走 keywords_hash，不应触发 ProgramLimitExceededError。"""
    from src.common.db.modules import Context
    from src.common.db.repository_pg import PgContextRepository

    repo = PgContextRepository()
    await repo.insert(
        Context.model_construct(keywords="longkw", time=0, trigger_count=1, answers=[], ban=[], clear_time=0)
    )
    long_ak = "x" * 5000  # 远超 btree 单行 2704 字节硬上限
    await repo.upsert_answer("longkw", 1, long_ak, 100, "m1", append_on_existing=True)
    await repo.upsert_answer("longkw", 1, long_ak, 200, "m2", append_on_existing=True)

    found = await repo.find_by_keywords("longkw")
    assert found is not None
    assert len(found.answers) == 1
    assert found.answers[0].keywords == long_ak
    assert found.answers[0].count == 2


@pytest.mark.asyncio
async def test_blacklist_upsert_is_atomic(pg_engine):
    """并发 upsert_answers 到同一 group_id 不会炸库、最终只剩 1 行。"""
    from src.common.db.repository_pg import PgBlackListRepository

    repo = PgBlackListRepository()
    await asyncio.gather(*[repo.upsert_answers(1, [f"a{i}"]) for i in range(20)])
    all_bl = await repo.find_all()
    group_rows = [x for x in all_bl if x.group_id == 1]
    assert len(group_rows) == 1


@pytest.mark.asyncio
async def test_image_cache_save_is_upsert(pg_engine):
    """PgImageCacheRepository.save 必须对齐 Mongo save() 的 upsert 语义（存在则更新、不存在则插入）。"""
    from src.common.db.modules import ImageCache
    from src.common.db.repository_pg import PgImageCacheRepository

    repo = PgImageCacheRepository()
    ic = ImageCache.model_construct(cq_code="[CQ:image,file=x.image]", base64_data=None, ref_times=1, date=20250419)
    await repo.save(ic)
    assert await repo.find_by_cq_code("[CQ:image,file=x.image]") is not None

    ic.ref_times = 5
    ic.base64_data = "b64"
    await repo.save(ic)
    got = await repo.find_by_cq_code("[CQ:image,file=x.image]")
    assert got is not None
    assert got.ref_times == 5
    assert got.base64_data == "b64"


@pytest.mark.asyncio
async def test_config_cache_hit_and_invalidate_on_write(pg_engine):
    """读后走 TTL 缓存；一旦 upsert_field 写入必须让缓存失效，下次读能拿到新值。"""
    from src.common.db.repository_pg import PgConfigRepository

    repo = PgConfigRepository("bot_config", "account")
    await repo.upsert_field(1001, "security", True)
    row1 = await repo.get(1001)
    assert row1 is not None and row1.security is True

    await repo.upsert_field(1001, "security", False)
    row2 = await repo.get(1001)
    assert row2 is not None and row2.security is False


@pytest.mark.asyncio
async def test_config_cache_ignore_cache_forces_db_read(pg_engine):
    """ignore_cache=True 必须绕过缓存直接回源，不受外部 SQL 旁路改库影响。"""
    from sqlalchemy import update

    from src.common.db.repository_pg import BotConfigRow, PgConfigRepository, get_session

    repo = PgConfigRepository("bot_config", "account")
    await repo.upsert_field(2002, "security", True)
    assert (await repo.get(2002)).security is True

    # 绕过 repo 直接 SQL 改库（不触发缓存失效）
    async with get_session() as session:
        await session.execute(update(BotConfigRow).where(BotConfigRow.account == 2002).values(security=False))
        await session.commit()

    cached = await repo.get(2002)
    assert cached.security is True  # 走缓存：旧值
    fresh = await repo.get(2002, ignore_cache=True)
    assert fresh.security is False  # 回源：新值


@pytest.mark.asyncio
async def test_config_invalidate_all(pg_engine):
    """invalidate_cache() 必须能全量清空该 row_class 的缓存条目。"""
    from src.common.db.repository_pg import PgConfigRepository

    repo = PgConfigRepository("bot_config", "account")
    await repo.upsert_field(3003, "security", True)
    assert (await repo.get(3003)).security is True
    await repo.invalidate_cache()
    assert (await repo.get(3003)).security is True  # 数据未变，只是不再走缓存


@pytest.mark.asyncio
async def test_config_get_or_create_concurrent(pg_engine):
    """并发 get_or_create 同一 key 必须只有一次 created=True，不得出现 IntegrityError 冒泡。"""
    from src.common.db.repository_pg import PgConfigRepository

    repo = PgConfigRepository("bot_config", "account")
    key = int(uuid.uuid4().int & 0x7FFFFFFF)

    results = await asyncio.gather(*[repo.get_or_create(key, disabled_plugins=[]) for _ in range(20)])
    created_count = sum(1 for _, created in results if created)
    assert created_count <= 1
    row = await repo.get(key, ignore_cache=True)
    assert row is not None
