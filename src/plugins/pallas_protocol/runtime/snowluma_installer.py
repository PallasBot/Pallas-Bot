"""SnowLuma 运行时下载与安装（GitHub Release zip / Linux tar.gz）。"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from src.common.utils.github_release import (
    fetch_github_releases,
    github_auth_headers,
    github_release_api_url,
    github_release_asset_url,
)
from src.common.utils.stream_download import (
    StreamDownloadProgress,
    format_download_byte_size,
    sync_stream_download_to_file,
)

from .installer import JobStatus, RuntimeManifest, _pick_release_asset_generic, _safe_extract_zip


def find_snowluma_program_dir(search_root: Path) -> Path | None:
    """查找含 ``index.mjs`` 的 SnowLuma 发行根（顶层或一层子目录，必要时浅层 rglob）。"""
    root = search_root.resolve()
    if not root.is_dir():
        return None
    if (root / "index.mjs").is_file():
        return root
    try:
        children = sorted(root.iterdir())
    except OSError:
        children = []
    for child in children:
        if child.is_dir() and (child / "index.mjs").is_file():
            return child
    for p in root.rglob("index.mjs"):
        if p.is_file():
            return p.parent
    return None


def _looks_like_http_url(value: str) -> bool:
    s = (value or "").strip()
    return s.startswith(("http://", "https://"))


def _asset_name_from_url(value: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(value)
    return Path(parsed.path).name.strip()


def default_snowluma_asset_name_for_tag(tag: str) -> str:
    """按平台与 tag 生成默认资产文件名（与 SnowLuma Release 命名一致）。"""
    t = (tag or "").strip()
    if not t:
        return ""
    if os.name == "nt":
        return f"SnowLuma-{t}-win-x64.zip"
    if sys.platform.startswith("linux"):
        return f"SnowLuma-{t}-linux-x64.tar.gz"
    return ""


def pick_snowluma_asset_from_release(release_json: dict[str, Any]) -> tuple[str, str] | None:
    """从 release JSON 中按当前平台选择完整包资产（排除名称中含 lite 的）。"""
    assets = release_json.get("assets")
    if not isinstance(assets, list):
        return None
    want_win = os.name == "nt"
    want_linux = sys.platform.startswith("linux")
    candidates: list[tuple[str, str]] = []
    for item in assets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        url = str(item.get("browser_download_url", "")).strip()
        if not name or not url:
            continue
        low = name.lower()
        if "lite" in low:
            continue
        if want_win and low.endswith(".zip") and "win-x64" in low:
            candidates.append((name, url))
        elif want_linux and low.endswith(".tar.gz") and "linux-x64" in low:
            candidates.append((name, url))
    if candidates:
        return candidates[0]
    return None


def _safe_extract_tar_gz(tar_path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "r:gz") as tf:
        tf.extractall(dest_dir, filter="data")


class SnowLumaRuntimeStore:
    """管理插件数据目录下的 SnowLuma 分发包（与 NapCat 运行时分离）。"""

    def __init__(self, data_dir: Path, config: Any) -> None:
        self._data_dir = data_dir
        self._config = config
        self._dist_dir = self._data_dir / "runtime_dist" / "snowluma"
        self._extract_root = self._data_dir / "runtime_extract" / "snowluma"
        self._manifest_path = self._data_dir / "snowluma_manifest.json"
        self._lock = asyncio.Lock()
        self._job_status: JobStatus = "idle"
        self._job_message = ""
        self._job_tag = ""
        self._job_task: asyncio.Task[None] | None = None

    def manifest_path(self) -> Path:
        return self._manifest_path

    def read_manifest(self) -> RuntimeManifest | None:
        if not self._manifest_path.exists():
            return None
        try:
            data = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        return RuntimeManifest.from_json(data)

    def resolved_program_dir(self) -> Path | None:
        m = self.read_manifest()
        if not m:
            return None
        prog = Path(m.program_dir)
        if prog.is_dir() and (prog / "index.mjs").is_file():
            return prog
        extract = Path(m.extract_root)
        if extract.is_dir():
            hit = find_snowluma_program_dir(extract)
            if hit is not None and hit.resolve() != prog.resolve():
                data = m.to_json()
                data["program_dir"] = str(hit.resolve())
                self._manifest_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            if hit is not None:
                return hit
        return prog if prog.is_dir() else None

    def job_snapshot(self) -> dict[str, Any]:
        return {"status": self._job_status, "message": self._job_message, "tag": self._job_tag}

    def is_busy(self) -> bool:
        return self._job_status in ("downloading", "extracting", "installing")

    def _github_token(self) -> str:
        return str(getattr(self._config, "pallas_protocol_github_token", "") or "").strip()

    def _repo(self) -> str:
        r = str(getattr(self._config, "pallas_protocol_snowluma_github_repo", "") or "").strip()
        return r or "SnowLuma/SnowLuma"

    def _release_tag(self) -> str:
        return str(getattr(self._config, "pallas_protocol_snowluma_release_tag", "") or "").strip()

    def _configured_asset(self) -> str:
        return str(getattr(self._config, "pallas_protocol_snowluma_release_asset", "") or "").strip()

    def _on_stream_download_progress(self, ev: StreamDownloadProgress) -> None:
        if ev["event"] == "percent":
            self._set_job(
                "downloading",
                f"SnowLuma 下载中 {ev['milestone_percent']}% "
                f"({format_download_byte_size(ev['received'])}/{format_download_byte_size(ev['total'])})",
            )
        elif ev["event"] == "complete":
            self._set_job("downloading", "下载完成，准备解压…")
        elif ev["event"] == "unknown_step":
            self._set_job(
                "downloading",
                f"下载中… ({format_download_byte_size(ev['received'])})",
            )

    def _set_job(self, status: JobStatus, message: str) -> None:
        self._job_status = status
        self._job_message = message

    async def download_and_install(
        self, *, client: httpx.AsyncClient | None = None, tag: str | None = None
    ) -> RuntimeManifest:
        async with self._lock:
            configured_asset = self._configured_asset()
            release_tag = tag.strip() if tag and tag.strip() else self._release_tag()
            self._job_tag = release_tag

            direct_asset_url = configured_asset if _looks_like_http_url(configured_asset) else ""
            asset_name = _asset_name_from_url(direct_asset_url) if direct_asset_url else configured_asset

            self._set_job("downloading", "准备下载 SnowLuma…")
            repo = self._repo()
            github_token = self._github_token()
            own_client = client is None
            hc = client or httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(600.0, connect=30.0),
                headers={"User-Agent": "Pallas-Bot-PallasProtocol/1.0"},
            )
            url = ""
            resolved_tag_for_manifest = release_tag
            try:
                _gh_headers = {**github_auth_headers(github_token), "User-Agent": "Pallas-Bot-PallasProtocol/1.0"}

                if direct_asset_url:
                    url = direct_asset_url
                    if not asset_name:
                        msg = "无法从 URL 解析资产文件名"
                        raise ValueError(msg)
                else:
                    tag_candidates: list[str] = []
                    if release_tag:
                        tag_candidates.append(release_tag)
                    tag_candidates.append("")

                    release_json: dict[str, Any] | None = None
                    used_tag = ""
                    for tag_try in tag_candidates:
                        rel_api = github_release_api_url(repo, tag_try)
                        rel_resp = await hc.get(rel_api, headers=_gh_headers)
                        if rel_resp.status_code == 200:
                            raw = rel_resp.json()
                            if isinstance(raw, dict):
                                release_json = raw
                                used_tag = str(raw.get("tag_name", "") or tag_try).strip()
                                break

                    if release_json is None:
                        msg = f"无法获取 SnowLuma Release（仓库 {repo}，tag={release_tag or 'latest'}）"
                        raise RuntimeError(msg)

                    resolved_tag_for_manifest = str(release_json.get("tag_name", "") or "").strip() or used_tag

                    if not asset_name:
                        picked = pick_snowluma_asset_from_release(release_json)
                        if picked is None:
                            pick = None
                            guess = default_snowluma_asset_name_for_tag(used_tag or release_tag)
                            if guess:
                                pick = _pick_release_asset_generic(release_json, guess)
                            if pick is None:
                                msg = (
                                    "当前平台未找到可用的 SnowLuma 资产"
                                    "（需要 Windows win-x64.zip 或 Linux linux-x64.tar.gz）"
                                )
                                raise RuntimeError(msg)
                            asset_name, url = pick
                        else:
                            asset_name, url = picked
                    else:
                        tag_for_url = used_tag or release_tag
                        picked_pair = _pick_release_asset_generic(release_json, asset_name)
                        if picked_pair is None:
                            url = github_release_asset_url(repo, asset_name, tag_for_url)
                        else:
                            asset_name, url = picked_pair

                self._dist_dir.mkdir(parents=True, exist_ok=True)
                dist_file = self._dist_dir / asset_name

                download_headers: dict[str, str] = {
                    "User-Agent": "Pallas-Bot-PallasProtocol/1.0",
                    **github_auth_headers(github_token),
                }

                self._set_job("downloading", f"下载 {asset_name}…")
                try:
                    await asyncio.to_thread(
                        sync_stream_download_to_file,
                        url,
                        dist_file,
                        follow_redirects=True,
                        timeout=httpx.Timeout(600.0, connect=30.0),
                        headers=download_headers,
                        on_progress=self._on_stream_download_progress,
                    )
                except httpx.HTTPStatusError as e:
                    code = e.response.status_code if e.response is not None else "?"
                    msg = f"SnowLuma 下载失败: HTTP {code}"
                    raise RuntimeError(msg) from e

                self._set_job("extracting", "解压 SnowLuma…")
                self._extract_root.mkdir(parents=True, exist_ok=True)
                stage = Path(tempfile.mkdtemp(prefix="snowluma_extract_", dir=str(self._extract_root)))
                try:
                    low = asset_name.lower()
                    if low.endswith(".zip"):
                        await asyncio.to_thread(_safe_extract_zip, dist_file, stage)
                    elif low.endswith(".tar.gz"):
                        await asyncio.to_thread(_safe_extract_tar_gz, dist_file, stage)
                    else:
                        msg = f"不支持的 SnowLuma 资产格式: {asset_name}"
                        raise RuntimeError(msg)

                    program_dir = find_snowluma_program_dir(stage)
                    if program_dir is None:
                        msg = "解压完成但未找到 index.mjs，请确认资产为官方 SnowLuma 发行包"
                        raise RuntimeError(msg)

                    self._extract_root.mkdir(parents=True, exist_ok=True)
                    final_root = self._extract_root / datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
                    if await asyncio.to_thread(final_root.exists):
                        shutil.rmtree(final_root, ignore_errors=True)
                    await asyncio.to_thread(shutil.move, str(stage), str(final_root))

                    tag_written = resolved_tag_for_manifest or self._job_tag or release_tag
                    manifest = RuntimeManifest(
                        program_dir=str(program_dir.resolve()),
                        extract_root=str(final_root.resolve()),
                        asset_name=asset_name,
                        release_tag=tag_written,
                        source_url=url,
                    )
                    self._manifest_path.write_text(
                        json.dumps(manifest.to_json(), ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    self._set_job("done", f"SnowLuma 安装完成: {manifest.program_dir}")
                    return manifest
                except Exception:
                    shutil.rmtree(stage, ignore_errors=True)
                    raise
            finally:
                if own_client:
                    await hc.aclose()

    def start_background_download(self, *, tag: str | None = None) -> None:
        if self.is_busy():
            msg = "已有 SnowLuma 下载或解压任务在执行"
            raise RuntimeError(msg)
        self._job_tag = tag.strip() if tag and tag.strip() else self._release_tag()

        async def _run() -> None:
            try:
                await self.download_and_install(tag=tag)
            except Exception as e:
                self._set_job("error", str(e))

        self._job_task = asyncio.create_task(_run())

    async def fetch_releases(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """获取 SnowLuma 仓库的 release 列表。"""
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"User-Agent": "Pallas-Bot-PallasProtocol/1.0"},
        ) as client:
            return await fetch_github_releases(self._repo(), client=client, limit=limit, token=self._github_token())
