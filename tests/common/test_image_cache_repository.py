"""
ImageCacheRepository 的 MongoDB 实现契约测试。
"""

from __future__ import annotations

import pytest

from pallas.core.foundation.db.modules import ImageCache
from pallas.core.foundation.db.repository import ImageCachePrunePolicy, ImageCacheRepository
from pallas.core.foundation.db.repository_impl import MongoImageCacheRepository


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
async def test_find_by_content_hash_resolves_cache_without_exposing_cq_code(beanie_fixture):
    repo = MongoImageCacheRepository()
    await repo.insert(ImageCache(cq_code="[CQ:image,file=private.image]", content_hash="a" * 64, blob_data=b"image"))

    found = await repo.find_by_content_hash("a" * 64)

    assert found is not None
    assert bytes(found.blob_data or b"") == b"image"


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
async def test_touch_increments_ref_and_refreshes_date_without_replacing_blob(beanie_fixture):
    repo = MongoImageCacheRepository()
    await repo.insert(ImageCache(cq_code="touch", blob_data=b"original", ref_times=1, date=20260101))

    await repo.touch("touch", date=20260810)

    found = await repo.find_by_cq_code("touch")
    assert found is not None
    assert found.ref_times == 2
    assert found.date == 20260810
    assert bytes(found.blob_data or b"") == b"original"


@pytest.mark.asyncio
async def test_find_latest_with_blob_skips_empty_cache_entries(beanie_fixture):
    repo = MongoImageCacheRepository()
    await repo.insert(ImageCache(cq_code="[CQ:image,file=empty.image]", blob_data=None, ref_times=9, date=20260806))
    expected = ImageCache(cq_code="[CQ:image,file=ready.image]", blob_data=b"image", ref_times=1, date=20260805)
    await repo.insert(expected)

    found = await repo.find_latest_with_blob()

    assert found is not None
    assert found.cq_code == expected.cq_code
    assert found.blob_data == b"image"


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


@pytest.mark.asyncio
async def test_prune_applies_retention_tiers_and_byte_limit(beanie_fixture):
    repo = MongoImageCacheRepository()
    rows = [
        ImageCache(cq_code="absolute-old", blob_data=b"a" * 4, ref_times=9, date=20260101),
        ImageCache(cq_code="single-old", blob_data=b"b" * 4, ref_times=1, date=20260701),
        ImageCache(cq_code="single-new", blob_data=b"c" * 4, ref_times=1, date=20260801),
        ImageCache(cq_code="popular-oldest", blob_data=b"d" * 4, ref_times=5, date=20260720),
        ImageCache(cq_code="popular-newest", blob_data=b"e" * 4, ref_times=5, date=20260802),
    ]
    for row in rows:
        await repo.insert(row)

    result = await repo.prune(
        ImageCachePrunePolicy(
            single_use_before=20260711,
            absolute_before=20260512,
            max_blob_bytes=8,
            batch_size=2,
        )
    )

    assert result.deleted_rows == 3
    assert result.deleted_blob_bytes == 12
    assert result.remaining_blob_bytes == 8
    assert await repo.find_by_cq_code("absolute-old") is None
    assert await repo.find_by_cq_code("single-old") is None
    assert await repo.find_by_cq_code("single-new") is None
    assert await repo.find_by_cq_code("popular-oldest") is not None
    assert await repo.find_by_cq_code("popular-newest") is not None
