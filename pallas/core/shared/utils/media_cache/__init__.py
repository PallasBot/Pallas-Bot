import asyncio
import re
from datetime import datetime, timedelta

import httpx
from nonebot import get_driver, logger
from nonebot.adapters.onebot.v11 import MessageSegment

from pallas.core.foundation.db import ImageCache, make_image_cache_repository
from pallas.core.shared.utils import HTTPXClient

image_cache_repo = make_image_cache_repository()
_image_capture_queue: asyncio.Queue[MessageSegment] | None = None
_image_capture_tasks: list[asyncio.Task[None]] = []
_image_capture_dropped: int = 0
_IMAGE_CAPTURE_QUEUE_MAX = 1024
_IMAGE_CAPTURE_BOUND = False


def image_capture_worker_count() -> int:
    from pallas.core.foundation.db.pool_budget import cap_by_pg_pool

    return max(1, min(3, cap_by_pg_pool(2, workload_fraction=0.06)))


def image_capture_under_load() -> bool:
    from packages.repeater.learn_queue import learn_queue_under_pressure
    from pallas.core.foundation.db.pool_budget import pg_pool_under_pressure
    from pallas.core.platform.ingress.message_load import should_pause_tasks

    return pg_pool_under_pressure(threshold=0.15) or learn_queue_under_pressure() or should_pause_tasks()


def image_capture_queue() -> asyncio.Queue[MessageSegment]:
    global _image_capture_queue
    if _image_capture_queue is None:
        _image_capture_queue = asyncio.Queue(maxsize=_IMAGE_CAPTURE_QUEUE_MAX)
    return _image_capture_queue


def _image_capture_workers_running() -> bool:
    return bool(_image_capture_tasks) and any(not task.done() for task in _image_capture_tasks)


async def _insert_image_io(image_seg: MessageSegment) -> None:
    """处理一条图片消息：下载成功才落盘（避免 issue #224 的 99.5% NULL 占位行）。"""
    cq_code = re.sub(r"\.image,.+?\]", ".image]", str(image_seg))
    cache = await image_cache_repo.find_by_cq_code(cq_code)
    if cache is None:
        # 第一次见到这张图：背压下放弃下载（避免在高峰期烧流量），
        # 否则尝试下载并直接以二进制形式落盘——这是 issue #223 BYTEA 改造的入口。
        if image_capture_under_load():
            return
        url = image_seg.data.get("url")
        if not url:
            return
        try:
            rsp = await HTTPXClient.get(url)
        except Exception as e:
            # 临时的网络问题（超时 / DNS / 连接 reset）或 HTTPX 级别异常——
            # 行为与"非 200 响应"对齐：放弃缓存这张图，不写 NULL 占位行（issue #224）。
            # 外层 run_image_capture_consumer 还会兜底 logger.warning，但这里精细化一级
            # 便于排查"为什么某张图没缓存"时区分网络/业务失败。
            logger.warning("image cache download error: cq_code={} err={}", cq_code, e)
            return
        if not rsp or rsp.status_code != httpx.codes.OK:
            return  # 下载失败就不缓存这张图，让它保持"未缓存"状态
        cache = ImageCache(
            cq_code=cq_code,
            blob_data=rsp.content,
            ref_times=1,
            date=int(str(datetime.now().date()).replace("-", "")),
        )
        await image_cache_repo.insert(cache)
        return
    # 已有缓存：只累加 ref_times + 刷鲜日期，不再补下载
    # （补下载的"第三次后才下载"逻辑在历史里制造了 99.5% NULL 行，issue #224）
    cache.ref_times += 1
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
    """按 cq_code 取出缓存的二进制图片；没有缓存或缓存为空时返回 None。"""
    cache = await image_cache_repo.find_by_cq_code(cq_code)
    if not cache:
        return None
    return cache.blob_data


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
