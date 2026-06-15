import asyncio
import base64
import re
from datetime import datetime, timedelta

import httpx
from nonebot import get_driver, logger
from nonebot.adapters.onebot.v11 import MessageSegment

from src.foundation.db import ImageCache, make_image_cache_repository
from src.shared.utils import HTTPXClient

image_cache_repo = make_image_cache_repository()
_image_capture_queue: asyncio.Queue[MessageSegment] | None = None
_image_capture_tasks: list[asyncio.Task[None]] = []
_image_capture_dropped: int = 0
_IMAGE_CAPTURE_QUEUE_MAX = 1024
_IMAGE_CAPTURE_BOUND = False


def image_capture_worker_count() -> int:
    from src.foundation.db.pool_budget import cap_by_pg_pool

    return max(1, min(3, cap_by_pg_pool(2, workload_fraction=0.06)))


def image_capture_under_load() -> bool:
    from src.foundation.db.pool_budget import pg_pool_under_pressure
    from src.plugins.repeater.learn_queue import learn_queue_under_pressure

    return pg_pool_under_pressure(threshold=0.15) or learn_queue_under_pressure()


def image_capture_queue() -> asyncio.Queue[MessageSegment]:
    global _image_capture_queue
    if _image_capture_queue is None:
        _image_capture_queue = asyncio.Queue(maxsize=_IMAGE_CAPTURE_QUEUE_MAX)
    return _image_capture_queue


def _image_capture_workers_running() -> bool:
    return bool(_image_capture_tasks) and any(not task.done() for task in _image_capture_tasks)


async def _insert_image_io(image_seg: MessageSegment) -> None:
    cq_code = re.sub(r"\.image,.+?\]", ".image]", str(image_seg))
    cache = await image_cache_repo.find_by_cq_code(cq_code)
    if not cache:
        cache = ImageCache.model_construct(
            cq_code=cq_code, base64_data=None, ref_times=1, date=int(str(datetime.now().date()).replace("-", ""))
        )
        await image_cache_repo.insert(cache)
        return
    cache.ref_times += 1
    under_load = image_capture_under_load()
    if cache.ref_times > 2 and cache.base64_data is None and not under_load:
        url = image_seg.data.get("url")
        if url:
            rsp = await HTTPXClient.get(url)
            if rsp and rsp.status_code == httpx.codes.OK:
                cache.base64_data = base64.b64encode(rsp.content).decode()
    await image_cache_repo.save(cache)


async def run_image_capture_consumer() -> None:
    while True:
        image_seg = await image_capture_queue().get()
        try:
            await _insert_image_io(image_seg)
        except Exception as e:
            logger.warning("image cache capture failed: {}", e)
        finally:
            image_capture_queue().task_done()


async def start_image_capture_workers() -> None:
    global _image_capture_tasks
    if _image_capture_workers_running():
        return
    await stop_image_capture_workers()
    count = image_capture_worker_count()
    _image_capture_tasks = [
        asyncio.create_task(run_image_capture_consumer(), name=f"image_capture_consumer_{idx}") for idx in range(count)
    ]


async def stop_image_capture_workers() -> None:
    global _image_capture_tasks
    if not _image_capture_tasks:
        return
    tasks = list(_image_capture_tasks)
    _image_capture_tasks = []
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def ensure_image_capture_workers() -> None:
    bind_image_capture_lifecycle()
    if _image_capture_workers_running():
        return
    asyncio.create_task(start_image_capture_workers())


def bind_image_capture_lifecycle() -> None:
    global _IMAGE_CAPTURE_BOUND
    if _IMAGE_CAPTURE_BOUND:
        return
    _IMAGE_CAPTURE_BOUND = True
    driver = get_driver()

    @driver.on_shutdown
    async def _on_shutdown() -> None:
        await stop_image_capture_workers()


async def insert_image(image_seg: MessageSegment):
    global _image_capture_dropped
    if image_capture_under_load():
        return
    ensure_image_capture_workers()
    try:
        image_capture_queue().put_nowait(image_seg)
    except asyncio.QueueFull:
        _image_capture_dropped += 1
        if _image_capture_dropped == 1 or _image_capture_dropped % 200 == 0:
            logger.info(
                "image cache capture queue full (max={}), dropped={}",
                _IMAGE_CAPTURE_QUEUE_MAX,
                _image_capture_dropped,
            )


async def get_image(cq_code) -> bytes | None:
    cache = await image_cache_repo.find_by_cq_code(cq_code)
    if not cache:
        return None
    if cache.base64_data is None:
        return None
    return base64.b64decode(cache.base64_data)


async def clear_image_cache(days: int = 5, times: int = 3):
    idate = int(str((datetime.now() - timedelta(days=days)).date()).replace("-", ""))
    await image_cache_repo.delete_old(idate)
    await image_cache_repo.delete_low_ref(times)


async def reset_image_cache_runtime_state_for_tests() -> None:
    global _image_capture_queue, _image_capture_dropped
    await stop_image_capture_workers()
    _image_capture_queue = None
    _image_capture_dropped = 0


if __name__ == "__main__":
    asyncio.run(clear_image_cache(5, 3))
