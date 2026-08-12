import asyncio
import hashlib
import re
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

import httpx
from nonebot import get_driver, logger
from nonebot.adapters.onebot.v11 import MessageSegment

from pallas.core.foundation.db import ImageCache, make_image_cache_repository
from pallas.core.foundation.db.repository import ImageCachePrunePolicy, ImageCachePruneResult
from pallas.core.foundation.db.runtime import is_postgresql_backend
from pallas.core.foundation.logging.throttle import log_rate_limited
from pallas.core.platform.work_jobs.models import WorkJob
from pallas.core.platform.work_jobs.runtime import build_work_job_store
from pallas.core.shared.utils import HTTPXClient

image_cache_repo = make_image_cache_repository()
_image_capture_queue: asyncio.Queue[WorkJob] | None = None
_image_capture_tasks: list[asyncio.Task[None]] = []
_image_capture_dropped: int = 0
_IMAGE_CAPTURE_QUEUE_MAX = 1024
_IMAGE_CAPTURE_BOUND = False


def image_capture_queue() -> asyncio.Queue[WorkJob]:
    global _image_capture_queue
    if _image_capture_queue is None:
        _image_capture_queue = asyncio.Queue(maxsize=_IMAGE_CAPTURE_QUEUE_MAX)
    return _image_capture_queue


def _image_capture_workers_running() -> bool:
    return bool(_image_capture_tasks) and any(not task.done() for task in _image_capture_tasks)


def normalize_image_cq_code(image_seg: MessageSegment) -> str:
    return re.sub(r"\.image,.+?\]", ".image]", str(image_seg))


def is_valid_image_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    hostname = parsed.hostname
    return parsed.scheme in {"http", "https"} and bool(hostname) and "&" not in hostname and bool(parsed.path)


def image_capture_payload(image_seg: MessageSegment) -> dict[str, str] | None:
    cq_code = normalize_image_cq_code(image_seg)
    url = str(image_seg.data.get("url") or "").strip()
    if not cq_code or not is_valid_image_http_url(url):
        return None
    return {"cq_code": cq_code, "url": url}


async def handle_image_cache_capture(payload: dict[str, object]) -> None:
    """由 work 进程下载一条图片并写入缓存。"""
    cq_code = str(payload.get("cq_code") or "").strip()
    url = str(payload.get("url") or "").strip()
    if not cq_code:
        raise ValueError("image cache capture cq_code is required")
    if not is_valid_image_http_url(url):
        raise ValueError("image cache capture url must use a valid http or https URL")
    cache = await image_cache_repo.find_by_cq_code(cq_code)
    if cache is None:
        rsp = await HTTPXClient.get(url, raise_for_status=False)
        if not rsp or rsp.status_code != httpx.codes.OK:
            status = getattr(rsp, "status_code", None)
            log_rate_limited(
                logger,
                "warning",
                f"image_cache.download.{status or 'unknown'}",
                "image cache download skipped after HTTP failure status [{}]",
                status or "unknown",
            )
            return
        values = {
            "cq_code": cq_code,
            "content_hash": hashlib.sha256(rsp.content).hexdigest(),
            "blob_data": rsp.content,
            "ref_times": 1,
            "date": int(str(datetime.now().date()).replace("-", "")),
        }
        cache = ImageCache.model_construct(**values) if is_postgresql_backend() else ImageCache(**values)
        await image_cache_repo.insert(cache)
        return
    # 已有缓存：只累加 ref_times + 刷鲜日期，不重写大字段，也不再补下载
    # （补下载的"第三次后才下载"逻辑在历史里制造了 99.5% NULL 行，issue #224）
    today = int(datetime.now().date().strftime("%Y%m%d"))
    await image_cache_repo.touch(cq_code, date=today)


async def run_image_capture_consumer() -> None:
    while True:
        first = await image_capture_queue().get()
        jobs = [first]
        try:
            while len(jobs) < 64:
                try:
                    jobs.append(image_capture_queue().get_nowait())
                except asyncio.QueueEmpty:
                    break
            await build_work_job_store().enqueue_many(jobs)
        except Exception as e:
            logger.warning("image cache capture outbox batch failed count={}: {}", len(jobs), e)
            while True:
                await asyncio.sleep(0.2)
                try:
                    await build_work_job_store().enqueue_many(jobs)
                except Exception as retry_exc:
                    logger.warning("image cache capture outbox retry failed count={}: {}", len(jobs), retry_exc)
                    continue
                break
        finally:
            for _job in jobs:
                image_capture_queue().task_done()


async def start_image_capture_workers() -> None:
    global _image_capture_tasks
    if _image_capture_workers_running():
        return
    await stop_image_capture_workers()
    _image_capture_tasks = [asyncio.create_task(run_image_capture_consumer(), name="image_capture_outbox_writer")]


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


async def insert_image(
    image_seg: MessageSegment,
    *,
    bot_id: int = 0,
    group_id: int = 0,
    message_id: int = 0,
) -> None:
    global _image_capture_dropped
    payload = image_capture_payload(image_seg)
    if payload is None:
        return
    cq_hash = hashlib.sha256(payload["cq_code"].encode()).hexdigest()[:16]
    job = WorkJob.create(
        kind="image_cache.capture",
        payload=payload,
        idempotency_key=f"image_cache.capture:{int(bot_id)}:{int(group_id)}:{int(message_id)}:{cq_hash}",
    )
    ensure_image_capture_workers()
    try:
        image_capture_queue().put_nowait(job)
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


async def bind_image_content_hash(cq_code: str, content: bytes) -> str:
    content_hash = hashlib.sha256(content).hexdigest()
    await image_cache_repo.bind_content_hash(cq_code, content_hash)
    return content_hash


async def get_image_by_content_hash(content_hash: str) -> bytes | None:
    cache = await image_cache_repo.find_by_content_hash(content_hash)
    return bytes(cache.blob_data) if cache and cache.blob_data else None


async def get_latest_image() -> bytes | None:
    """取最近一张可发送的缓存图片。"""
    cache = await image_cache_repo.find_latest_with_blob()
    return cache.blob_data if cache else None


async def get_recent_images(limit: int) -> list[tuple[str, bytes]]:
    rows = await image_cache_repo.find_recent_with_blob(limit)
    return [(row.cq_code, bytes(row.blob_data)) for row in rows if row.blob_data]


async def clear_image_cache(days: int = 5, times: int = 3):
    idate = int(str((datetime.now() - timedelta(days=days)).date()).replace("-", ""))
    await image_cache_repo.delete_old(idate)
    await image_cache_repo.delete_low_ref(times)


async def prune_image_cache(*, today: date | None = None) -> ImageCachePruneResult:
    current = today or datetime.now().date()
    single_use_before = int((current - timedelta(days=30)).strftime("%Y%m%d"))
    absolute_before = int((current - timedelta(days=90)).strftime("%Y%m%d"))
    result = await image_cache_repo.prune(
        ImageCachePrunePolicy(
            single_use_before=single_use_before,
            absolute_before=absolute_before,
            max_blob_bytes=20 * 1024**3,
            batch_size=1000,
        )
    )
    logger.info(
        "image cache pruned rows={} bytes={} remaining_bytes={}",
        result.deleted_rows,
        result.deleted_blob_bytes,
        result.remaining_blob_bytes,
    )
    return result


async def reset_image_cache_runtime_state_for_tests() -> None:
    global _image_capture_queue, _image_capture_dropped
    await stop_image_capture_workers()
    _image_capture_queue = None
    _image_capture_dropped = 0


if __name__ == "__main__":
    asyncio.run(clear_image_cache(5, 3))
