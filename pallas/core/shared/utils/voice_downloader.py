import asyncio
import zipfile

import httpx
from nonebot import logger

from pallas.core.foundation.paths import RESOURCE_ROOT

VOICES_URLS = {
    "hf-mirror": "https://hf-mirror.com/pallasbot/Pallas-Bot/resolve/main/voices/Pallas.zip",
    "huggingface": "https://huggingface.co/pallasbot/Pallas-Bot/resolve/main/voices/Pallas.zip",
}

VOICES_DIR = RESOURCE_ROOT / "voices"
TEMP_ZIP_PATH = RESOURCE_ROOT / "voices_temp.zip"

VOICES = {
    "任命助理",
    "交谈1",
    "交谈2",
    "交谈3",
    "晋升后交谈1",
    "晋升后交谈2",
    "信赖提升后交谈1",
    "信赖提升后交谈2",
    "信赖提升后交谈3",
    "闲置",
    "干员报到",
    "精英化晋升1",
    "精英化晋升2",
    "编入队伍",
    "任命队长",
    "戳一下",
    "信赖触摸",
    "问候",
}

# 单源超时：后台下载也不宜无限挂起
_DOWNLOAD_TIMEOUT_SEC = 60.0

_background_ensure_task: asyncio.Task[None] | None = None


def voices_ready() -> bool:
    pallas_dir = VOICES_DIR / "Pallas"
    if not pallas_dir.is_dir():
        return False
    return all((pallas_dir / f"{file}.wav").is_file() for file in VOICES)


async def download_voices() -> bool:
    try:
        logger.info("[语音] 开始下载")

        RESOURCE_ROOT.mkdir(exist_ok=True)
        VOICES_DIR.mkdir(exist_ok=True)

        timeout = httpx.Timeout(_DOWNLOAD_TIMEOUT_SEC)
        limits = httpx.Limits(max_keepalive_connections=1, max_connections=1)
        download_success = False
        for source, url in VOICES_URLS.items():
            try:
                logger.info("[语音] 从 {} 下载", source)
                async with httpx.AsyncClient(timeout=timeout, limits=limits, follow_redirects=True) as client:
                    response = await client.get(url)
                    response.raise_for_status()

                    TEMP_ZIP_PATH.write_bytes(response.content)
                    logger.info("[语音] 已下载 {:.1f}MB，解压中", len(response.content) / 1024 / 1024)
                    download_success = True
                    break

            except (httpx.HTTPStatusError, httpx.RequestError, Exception) as e:
                logger.warning("[语音] 下载失败 source={} err={}", source, e)
                continue

        if not download_success:
            logger.error("[语音] 所有下载源均失败")
            return False

        with zipfile.ZipFile(TEMP_ZIP_PATH, "r") as zip_ref:
            zip_ref.extractall(VOICES_DIR)

        TEMP_ZIP_PATH.unlink(missing_ok=True)

        logger.info("[语音] 就绪")
        return True

    except Exception as e:
        logger.error("[语音] 下载异常: {}", e)
        if TEMP_ZIP_PATH.exists():
            try:
                TEMP_ZIP_PATH.unlink()
            except Exception:
                pass
        return False


async def ensure_voices(*, announce_missing: bool = True) -> bool:
    try:
        if voices_ready():
            return True

        if announce_missing:
            logger.info("[语音] 缺失，开始下载")
        return await download_voices()

    except Exception as e:
        logger.error("[语音] ensure 失败: {}", e)
        return False


async def _run_background_ensure_voices() -> None:
    try:
        # schedule 已提示「缺失，已调度」；此处不再重复「缺失」语义
        ok = await ensure_voices(announce_missing=False)
        if not ok:
            logger.warning("[语音] 后台就绪失败，相关功能将降级")
    except Exception as err:
        logger.warning("[语音] 后台就绪失败: {}", err)


def schedule_ensure_voices() -> None:
    """后台确保语音资源，不阻塞 NoneBot Application startup。"""
    global _background_ensure_task
    if voices_ready():
        return
    if _background_ensure_task is not None and not _background_ensure_task.done():
        logger.debug("[语音] 后台下载已在进行，跳过")
        return
    logger.info("[语音] 缺失，已调度后台下载（不阻塞启动）")
    loop = asyncio.get_running_loop()
    _background_ensure_task = loop.create_task(
        _run_background_ensure_voices(),
        name="ensure_voices",
    )
