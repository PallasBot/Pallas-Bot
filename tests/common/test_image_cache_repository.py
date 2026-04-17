"""
ImageCacheRepository 的 MongoDB 实现契约测试。
"""

from __future__ import annotations

import pytest

from src.common.db.modules import ImageCache
from src.common.db.repository import ImageCacheRepository
from src.common.db.repository_impl import MongoImageCacheRepository


def test_mongo_image_cache_satisfies_protocol():
    assert isinstance(MongoImageCacheRepository(), ImageCacheRepository)


@pytest.mark.asyncio
async def test_find_by_cq_code_not_found(beanie_fixture):
    repo = MongoImageCacheRepository()
    assert await repo.find_by_cq_code("[CQ:image,file=nonexistent.image]") is None


@pytest.mark.asyncio
async def test_insert_and_find(beanie_fixture):
    repo = MongoImageCacheRepository()
    cq = "[CQ:image,file=a.image]"

    await repo.insert(ImageCache(cq_code=cq))
    found = await repo.find_by_cq_code(cq)
    assert found is not None
    assert found.cq_code == cq
    assert found.ref_times == 1


@pytest.mark.asyncio
async def test_save_increments_ref_times(beanie_fixture):
    repo = MongoImageCacheRepository()
    cq = "[CQ:image,file=b.image]"

    cache = ImageCache(cq_code=cq)
    await repo.insert(cache)

    found = await repo.find_by_cq_code(cq)
    assert found is not None
    found.ref_times += 2
    await repo.save(found)

    found_again = await repo.find_by_cq_code(cq)
    assert found_again is not None
    assert found_again.ref_times == 3


@pytest.mark.asyncio
async def test_delete_low_ref(beanie_fixture):
    repo = MongoImageCacheRepository()

    keep = ImageCache(cq_code="[CQ:image,file=keep.image]", ref_times=5)
    drop = ImageCache(cq_code="[CQ:image,file=drop.image]", ref_times=1)
    await repo.insert(keep)
    await repo.insert(drop)

    await repo.delete_low_ref(ref_threshold=3)

    assert await repo.find_by_cq_code("[CQ:image,file=keep.image]") is not None
    assert await repo.find_by_cq_code("[CQ:image,file=drop.image]") is None


@pytest.mark.asyncio
async def test_delete_old(beanie_fixture):
    repo = MongoImageCacheRepository()

    old = ImageCache(cq_code="[CQ:image,file=old.image]")
    old.date = 20200101
    fresh = ImageCache(cq_code="[CQ:image,file=fresh.image]")
    fresh.date = 20991231
    await repo.insert(old)
    await repo.insert(fresh)

    await repo.delete_old(before_date=20250101)

    assert await repo.find_by_cq_code("[CQ:image,file=old.image]") is None
    assert await repo.find_by_cq_code("[CQ:image,file=fresh.image]") is not None
