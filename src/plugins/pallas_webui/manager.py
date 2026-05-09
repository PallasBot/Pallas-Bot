"""控制台静态资源：默认目录 data/pallas_webui/public，可选 zip 直链下载解压。"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

import httpx
from nonebot import logger

from src.common.paths import plugin_data_dir
from src.common.utils.format_exception import format_exception_for_log
from src.common.utils.github_release import (
    fetch_latest_release,
    fetch_latest_release_tag_via_github_web,
    github_auth_headers,
    github_release_api_url,
    github_release_asset_url,
    github_release_asset_url_candidates,
)
from src.common.utils.stream_download import (
    StreamDownloadProgress,
    format_download_byte_size,
    sync_stream_download_to_file,
)


async def resolve_github_release_asset_urls(
    repo: str,
    preferred_asset: str,
    tag: str = "",
    *,
    token: str = "",
) -> list[str]:
    """先查 release 资产列表再选下载 URL；失败时回退到直链候选。"""
    preferred = (preferred_asset or "").strip()
    if not preferred:
        raise ValueError("发布资产名不能为空")
    candidates: list[str] = []
    release_apis = [github_release_api_url(repo, tag)]
    if (tag or "").strip():
        release_apis.append(github_release_api_url(repo, ""))
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(30.0, connect=10.0),
        headers={"User-Agent": "Pallas-Bot-PallasWebUI/1.0"},
    ) as client:
        auth_headers = github_auth_headers(token)
        for api in release_apis:
            try:
                resp = await client.get(api, headers=auth_headers)
            except Exception as e:
                # API 失败仍会追加 releases/download 直链候选，默认不打 WARNING 以免刷屏
                logger.debug(
                    "Pallas 控制台: GitHub Release API 请求异常（将尝试直链）api={} err={}",
                    api,
                    format_exception_for_log(e),
                )
                continue
            if resp.status_code != 200:
                logger.debug(
                    "Pallas 控制台: GitHub Release API 非 200（将尝试直链）status={} api={}",
                    resp.status_code,
                    api,
                )
                continue
            data = resp.json()
            assets = data.get("assets")
            if not isinstance(assets, list):
                continue
            urls: dict[str, str] = {}
            for item in assets:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                url = str(item.get("browser_download_url", "")).strip()
                if not name or not url:
                    continue
                urls[name] = url
            if preferred in urls:
                candidates.append(urls[preferred])
            elif urls:
                for name, url in urls.items():
                    if name.lower().endswith(".zip"):
                        candidates.append(url)
                        break
    # 追加直链候选
    candidates.extend(github_release_asset_url_candidates(repo, preferred, tag))
    dedup: list[str] = []
    seen: set[str] = set()
    for u in candidates:
        if u in seen:
            continue
        seen.add(u)
        dedup.append(u)
    return dedup


def webui_public_path() -> Path:
    return plugin_data_dir("pallas_webui") / "public"


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


def _safe_extract_zip(zf: zipfile.ZipFile, extract_root: Path) -> None:
    """防 Zip Slip：逐成员校验解析后路径必须落在 extract_root 内部。"""
    root = extract_root.resolve()
    for member in zf.infolist():
        raw_name = member.filename or ""
        if not raw_name:
            continue
        # 拒绝绝对路径与 Windows 驱动器/UNC 前缀
        if raw_name.startswith(("/", "\\")) or (len(raw_name) >= 2 and raw_name[1] == ":"):
            msg = f"禁止的 ZIP 路径（绝对路径）: {raw_name}"
            raise ValueError(msg)
        dest = (root / raw_name).resolve()
        if dest != root and not dest.is_relative_to(root):
            msg = f"禁止的 ZIP 路径（越界）: {raw_name}"
            raise ValueError(msg)
        if member.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, dest.open("wb") as dst:
            shutil.copyfileobj(src, dst)


def _sync_extract_dist_zip_file(zip_path: Path, public_dir: Path) -> None:
    public_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tpath = Path(tmp)
        extract_root = tpath / "extracted"
        extract_root.mkdir()
        with zipfile.ZipFile(zip_path) as zf:
            _safe_extract_zip(zf, extract_root)
        source = _resolved_extract_root(extract_root)
        if public_dir.exists():
            shutil.rmtree(public_dir)
        public_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, public_dir, dirs_exist_ok=True)


def _sync_write_dist_from_zip_bytes(public_dir: Path, content: bytes) -> None:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tf:
        tf.write(content)
        zip_path = Path(tf.name)
    try:
        _sync_extract_dist_zip_file(zip_path, public_dir)
    finally:
        zip_path.unlink(missing_ok=True)


def _unlink_ignore_missing(path: Path) -> None:
    path.unlink(missing_ok=True)


def _webui_download_progress_log(ev: StreamDownloadProgress) -> None:
    if ev["event"] == "percent":
        logger.info(
            "Pallas 控制台: WebUI dist 下载进度 {}%（{}/{}）",
            ev["milestone_percent"],
            format_download_byte_size(ev["received"]),
            format_download_byte_size(ev["total"]),
        )
    elif ev["event"] == "unknown_step":
        logger.info(
            "Pallas 控制台: WebUI dist 已下载 {}（服务器未提供文件大小）",
            format_download_byte_size(ev["received"]),
        )
    elif ev["event"] == "complete":
        if ev["total"] is not None:
            logger.info(
                "Pallas 控制台: WebUI dist 下载完成 {} / {}",
                format_download_byte_size(ev["received"]),
                format_download_byte_size(ev["total"]),
            )
        elif ev["received"] > 0:
            logger.info(
                "Pallas 控制台: WebUI dist 下载完成 {}",
                format_download_byte_size(ev["received"]),
            )


def _sync_download_webui_zip(url: str, dest: Path, *, follow_redirects: bool) -> None:
    sync_stream_download_to_file(
        url,
        dest,
        follow_redirects=follow_redirects,
        timeout=httpx.Timeout(300.0, connect=60.0),
        on_progress=_webui_download_progress_log,
    )


async def download_and_extract_dist_zip(public_dir: Path, url: str, *, follow_redirects: bool = True) -> bool:
    url = (url or "").strip()
    if not url:
        return False
    preview = url if len(url) <= 200 else url[:197] + "..."
    logger.info("Pallas 控制台: 正在下载 WebUI dist {}", preview)

    tmp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    zip_path = Path(tmp_zip.name)
    tmp_zip.close()

    try:
        await asyncio.to_thread(_sync_download_webui_zip, url, zip_path, follow_redirects=follow_redirects)
        await asyncio.to_thread(_sync_extract_dist_zip_file, zip_path, public_dir)
        logger.info("Pallas 控制台: 已解压 dist 到 data/pallas_webui/public")
    finally:
        await asyncio.to_thread(_unlink_ignore_missing, zip_path)

    return True


def webui_version_path() -> Path:
    return plugin_data_dir("pallas_webui") / "version.json"


def get_webui_dist_version() -> str:
    import json

    path = webui_public_path() / "console-version.json"
    if not path.exists():
        return ""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return str(raw.get("version") or raw.get("tag") or "").strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def get_installed_webui_version() -> dict:
    import json

    path = webui_version_path()
    result: dict = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            result = raw if isinstance(raw, dict) else {}
        except Exception:  # noqa: BLE001
            pass
    # version.json 没有 tag 时，从 dist 的 console-version.json 补充
    if not result.get("tag"):
        dist_ver = get_webui_dist_version()
        if dist_ver:
            result = {**result, "tag": dist_ver}
    return result


def save_installed_webui_version(tag: str, asset_url: str = "") -> None:
    """下载成功后写入版本信息。"""
    import json
    import time

    path = webui_version_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "tag": (tag or "").strip(),
        "asset_url": (asset_url or "").strip(),
        "installed_at": time.time(),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


_BOT_ROOT = Path(__file__).resolve().parents[3]


def get_bot_current_version() -> dict:
    import subprocess

    root = _BOT_ROOT
    tag = ""
    commit = ""
    try:
        tag = subprocess.check_output(
            ["git", "describe", "--tags", "--exact-match"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:  # noqa: BLE001
        pass
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:  # noqa: BLE001
        pass
    return {"tag": tag, "commit": commit}


async def fetch_latest_bot_release(repo: str = "PallasBot/Pallas-Bot", *, token: str = "") -> dict:
    try:
        data = await fetch_latest_release(
            repo,
            user_agent="Pallas-Bot-PallasWebUI/1.0",
            token=token,
            include_asset_url=False,
        )
        return {"tag": data["tag"], "html_url": data["html_url"]}
    except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError) as first_err:
        try:
            fb = await fetch_latest_release_tag_via_github_web(
                repo,
                token=token,
                user_agent="Pallas-Bot-PallasWebUI/1.0",
            )
            logger.debug(
                "Pallas 控制台: GitHub Release API 不可用，已用 github.com/releases/latest 兜底（Bot）tag={}",
                fb["tag"],
            )
            return {"tag": fb["tag"], "html_url": fb["html_url"]}
        except Exception:
            raise first_err from None


async def fetch_latest_webui_release(repo: str, *, token: str = "", asset_name: str = "dist.zip") -> dict:
    asset_clean = (asset_name or "").strip() or "dist.zip"
    try:
        return await fetch_latest_release(
            repo,
            user_agent="Pallas-Bot-PallasWebUI/1.0",
            token=token,
            preferred_asset_name=asset_clean,
            include_asset_url=True,
        )
    except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError) as first_err:
        try:
            fb = await fetch_latest_release_tag_via_github_web(
                repo,
                token=token,
                user_agent="Pallas-Bot-PallasWebUI/1.0",
            )
            tag_fb = fb["tag"]
            asset_url_fb = github_release_asset_url(repo, asset_clean, tag_fb)
            logger.debug(
                "Pallas 控制台: GitHub Release API 不可用，已用 github.com/releases/latest 兜底（WebUI）tag={}",
                tag_fb,
            )
            return {"tag": tag_fb, "html_url": fb["html_url"], "asset_url": asset_url_fb}
        except Exception:
            raise first_err from None
