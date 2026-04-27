"""控制台静态资源：默认目录 data/pallas_webui/public，可选 zip 直链下载解压。"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote

import httpx
from nonebot import logger

from src.common.paths import plugin_data_dir


def _shared_github_auth_headers() -> dict[str, str]:
    """优先复用 pallas_protocol 的 GitHub token。"""
    token = (os.environ.get("PALLAS_PROTOCOL_GITHUB_TOKEN") or "").strip()
    if not token:
        try:
            from nonebot import get_plugin_config

            from src.plugins.pallas_protocol.config import Config as ProtocolConfig

            cfg = get_plugin_config(ProtocolConfig)
            token = str(getattr(cfg, "pallas_protocol_github_token", "") or "").strip()
        except Exception:  # noqa: BLE001
            token = ""
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def github_release_asset_url(repo: str, asset_name: str, tag: str = "") -> str:
    owner_part, _, name_part = (repo or "").strip().partition("/")
    if not owner_part or not name_part:
        msg = f"无效的 GitHub 仓库名: {repo!r}，应为 Owner/Repo"
        raise ValueError(msg)
    encoded = quote((asset_name or "").strip(), safe=".")
    if not encoded:
        raise ValueError("发布资产名不能为空")
    if not (tag or "").strip():
        return f"https://github.com/{owner_part}/{name_part}/releases/latest/download/{encoded}"
    return f"https://github.com/{owner_part}/{name_part}/releases/download/{(tag or '').strip()}/{encoded}"


def github_release_asset_url_candidates(repo: str, asset_name: str, tag: str = "") -> list[str]:
    """返回可尝试的下载地址：优先 tag，其次 latest。"""
    out: list[str] = []
    tag_clean = (tag or "").strip()
    if tag_clean:
        out.append(github_release_asset_url(repo, asset_name, tag_clean))
    out.append(github_release_asset_url(repo, asset_name, ""))
    dedup: list[str] = []
    seen: set[str] = set()
    for u in out:
        if u in seen:
            continue
        seen.add(u)
        dedup.append(u)
    return dedup


def _github_release_api_url(repo: str, tag: str = "") -> str:
    owner_part, _, name_part = (repo or "").strip().partition("/")
    if not owner_part or not name_part:
        msg = f"无效的 GitHub 仓库名: {repo!r}，应为 Owner/Repo"
        raise ValueError(msg)
    if not (tag or "").strip():
        return f"https://api.github.com/repos/{owner_part}/{name_part}/releases/latest"
    return f"https://api.github.com/repos/{owner_part}/{name_part}/releases/tags/{(tag or '').strip()}"


async def resolve_github_release_asset_urls(repo: str, preferred_asset: str, tag: str = "") -> list[str]:
    """先查 release 资产列表再选下载 URL；失败时回退到直链候选。"""
    preferred = (preferred_asset or "").strip()
    if not preferred:
        raise ValueError("发布资产名不能为空")
    candidates: list[str] = []
    release_apis = [_github_release_api_url(repo, tag)]
    if (tag or "").strip():
        release_apis.append(_github_release_api_url(repo, ""))
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(30.0, connect=10.0),
        headers={"User-Agent": "Pallas-Bot-PallasWebUI/1.0"},
    ) as client:
        auth_headers = _shared_github_auth_headers()
        for api in release_apis:
            try:
                resp = await client.get(api, headers=auth_headers)
            except Exception:
                continue
            if resp.status_code != 200:
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


async def fetch_latest_bot_release(repo: str = "PallasBot/Pallas-Bot") -> dict:
    api_url = _github_release_api_url(repo)
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(15.0, connect=8.0),
        headers={"User-Agent": "Pallas-Bot-PallasWebUI/1.0"},
    ) as client:
        resp = await client.get(api_url, headers=_shared_github_auth_headers())
        resp.raise_for_status()
        data = resp.json()
    tag = str(data.get("tag_name") or "").strip()
    html_url = str(data.get("html_url") or "").strip()
    return {"tag": tag, "html_url": html_url}


async def fetch_latest_webui_release(repo: str) -> dict:
    api_url = _github_release_api_url(repo)
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(15.0, connect=8.0),
        headers={"User-Agent": "Pallas-Bot-PallasWebUI/1.0"},
    ) as client:
        resp = await client.get(api_url, headers=_shared_github_auth_headers())
        resp.raise_for_status()
        data = resp.json()
    tag = str(data.get("tag_name") or "").strip()
    html_url = str(data.get("html_url") or "").strip()
    assets = data.get("assets") or []
    asset_url = ""
    for item in assets:
        if isinstance(item, dict) and str(item.get("name", "")).lower().endswith(".zip"):
            asset_url = str(item.get("browser_download_url", "")).strip()
            break
    return {"tag": tag, "html_url": html_url, "asset_url": asset_url}
