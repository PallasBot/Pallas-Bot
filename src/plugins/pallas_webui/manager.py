"""控制台静态资源：默认目录 data/pallas_webui/public，可选 zip 直链下载解压。"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import zipfile
from pathlib import Path

import httpx
from nonebot import logger

from src.common.paths import plugin_data_dir


def webui_public_path() -> Path:
    return plugin_data_dir("pallas_webui") / "public"


def migrate_legacy_dist_if_needed(public_dir: Path) -> bool:
    """兼容历史部署路径 src/plugins/pallas_webui/dist -> data/pallas_webui/public。"""
    if check_webui_exists(public_dir):
        return False
    legacy_dist = Path(__file__).resolve().parent / "dist"
    if not check_webui_exists(legacy_dist):
        return False
    if public_dir.exists():
        shutil.rmtree(public_dir)
    public_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(legacy_dist, public_dir, dirs_exist_ok=True)
    logger.warning(
        "Pallas 控制台: 检测到历史 dist 路径，已迁移到 data/pallas_webui/public；"
        "后续请将前端产物发布到 data/<plugin_name>/public。",
    )
    return True


def check_webui_exists(path: Path) -> bool:
    return (path / "index.html").is_file()


def _resolved_extract_root(archive_dir: Path) -> Path:
    if (archive_dir / "index.html").is_file():
        return archive_dir
    subdirs = [d for d in archive_dir.iterdir() if d.is_dir()]
    if len(subdirs) == 1 and (subdirs[0] / "index.html").is_file():
        return subdirs[0]
    if len(subdirs) == 1:
        return subdirs[0]
    return archive_dir


def _sync_write_dist_from_zip_bytes(public_dir: Path, content: bytes) -> None:
    public_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tpath = Path(tmp)
        zip_path = tpath / "webui.zip"
        zip_path.write_bytes(content)
        with zipfile.ZipFile(zip_path) as zf:
            extract_root = tpath / "extracted"
            extract_root.mkdir()
            zf.extractall(extract_root)
        source = _resolved_extract_root(extract_root)
        if public_dir.exists():
            shutil.rmtree(public_dir)
        public_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, public_dir, dirs_exist_ok=True)


async def download_and_extract_dist_zip(public_dir: Path, url: str, *, follow_redirects: bool = True) -> bool:
    url = (url or "").strip()
    if not url:
        return False
    async with httpx.AsyncClient(follow_redirects=follow_redirects, timeout=300.0) as c:
        r = await c.get(url)
        r.raise_for_status()
        content = r.content
    await asyncio.to_thread(_sync_write_dist_from_zip_bytes, public_dir, content)
    logger.info("Pallas 控制台: 已解压 dist 到 data/pallas_webui/public")
    return True
