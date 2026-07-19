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


async def download_voices() -> bool:
    try:
        logger.info("[语音] 开始下载")

        RESOURCE_ROOT.mkdir(exist_ok=True)
        VOICES_DIR.mkdir(exist_ok=True)

        timeout = httpx.Timeout(300.0)
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
                logger.warning("voices: download failed source={} err={}", source, e)
                continue

        if not download_success:
            logger.error("voices: all download sources failed")
            raise RuntimeError("all voice download sources failed")

        with zipfile.ZipFile(TEMP_ZIP_PATH, "r") as zip_ref:
            zip_ref.extractall(VOICES_DIR)

        TEMP_ZIP_PATH.unlink()

        logger.info("[语音] 就绪")
        return True

    except Exception as e:
        logger.error("voices: download error: {}", e)
        if TEMP_ZIP_PATH.exists():
            try:
                TEMP_ZIP_PATH.unlink()
            except Exception:
                pass
        return False


async def ensure_voices() -> bool:
    try:
        pallas_dir = VOICES_DIR / "Pallas"
        if pallas_dir.exists():
            if all((pallas_dir / f"{file}.wav").exists() for file in VOICES):
                return True

        logger.info("[语音] 缺失，开始下载")
        return await download_voices()

    except Exception as e:
        logger.error("voices: ensure failed: {}", e)
        return False
