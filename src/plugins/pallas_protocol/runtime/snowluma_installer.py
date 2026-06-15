"""SnowLuma 运行时下载与安装。"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

import httpx

from src.shared.utils.github_release import (
    fetch_github_releases,
    github_auth_headers,
    github_release_api_url,
    github_release_asset_url,
)
from src.shared.utils.stream_download import (
    StreamDownloadProgress,
    format_download_byte_size,
    sync_stream_download_to_file,
)

from .installer import (
    JobStatus,
    RuntimeManifest,
    _pick_release_asset_generic,
    _safe_extract_zip,
    unlink_files_in_dir,
)
from .tag_paths import sanitize_release_tag_for_path


def find_snowluma_program_dir(search_root: Path) -> Path | None:
    """查找含 ``index.mjs`` 的 SnowLuma 发行根。"""
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


def default_snowluma_asset_name_for_tag(tag: str, *, target_platform: str | None = None) -> str:
    """按目标平台与 tag 生成默认资产文件名。"""
    t = (tag or "").strip()
    if not t:
        return ""
    plat = (target_platform or "auto").strip().lower()
    if plat in ("windows-amd64", "windows"):
        return f"SnowLuma-{t}-win-x64.zip"
    if plat == "linux-arm64":
        return f"SnowLuma-{t}-linux-arm64.tar.gz"
    if plat in ("linux-amd64", "linux"):
        return f"SnowLuma-{t}-linux-x64.tar.gz"
    if plat in ("", "auto"):
        if os.name == "nt":
            return f"SnowLuma-{t}-win-x64.zip"
        if sys.platform.startswith("linux"):
            mach = (platform.machine() or "").lower()
            if "arm" in mach or "aarch64" in mach:
                return f"SnowLuma-{t}-linux-arm64.tar.gz"
            return f"SnowLuma-{t}-linux-x64.tar.gz"
    return ""


def pick_snowluma_asset_from_release(
    release_json: dict[str, Any],
    *,
    target_platform: str | None = None,
) -> tuple[str, str] | None:
    """从 release JSON 中选择完整包资产。"""
    assets = release_json.get("assets")
    if not isinstance(assets, list):
        return None
    plat = (target_platform or "auto").strip().lower()
    if plat in ("windows-amd64", "windows"):
        want_win, want_linux_amd, want_linux_arm = True, False, False
    elif plat == "linux-amd64":
        want_win, want_linux_amd, want_linux_arm = False, True, False
    elif plat == "linux-arm64":
        want_win, want_linux_amd, want_linux_arm = False, False, True
    else:
        want_win = os.name == "nt"
        want_linux_amd = sys.platform.startswith("linux")
        want_linux_arm = want_linux_amd and (
            "arm" in (platform.machine() or "").lower() or "aarch64" in (platform.machine() or "").lower()
        )
        if want_linux_arm:
            want_linux_amd = False
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
        ok = False
        if want_win and low.endswith(".zip") and "win-x64" in low:
            ok = True
        elif (
            want_linux_arm and low.endswith(".tar.gz") and ("arm64" in low or "aarch64" in low or "linux-arm64" in low)
        ):
            ok = True
        elif want_linux_amd and low.endswith(".tar.gz") and "linux-x64" in low and "arm" not in low:
            ok = True
        if ok:
            candidates.append((name, url))
    if candidates:
        return candidates[0]
    return None


def _safe_extract_tar_gz(tar_path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "r:gz") as tf:
        tf.extractall(dest_dir, filter="data")


class SnowLumaRuntimeStore:
    """管理插件数据目录下的 SnowLuma 分发包。"""

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

    def clear_dist_file_cache(self) -> int:
        """删除已下载的发行包文件，不删 runtime_extract 与 manifest。"""
        return unlink_files_in_dir(self._dist_dir)

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
        self,
        *,
        client: httpx.AsyncClient | None = None,
        tag: str | None = None,
        target_platform: str | None = None,
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
                        picked = pick_snowluma_asset_from_release(
                            release_json,
                            target_platform=target_platform,
                        )
                        if picked is None:
                            pick = None
                            guess = default_snowluma_asset_name_for_tag(
                                used_tag or release_tag,
                                target_platform=target_platform,
                            )
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

                    if find_snowluma_program_dir(stage) is None:
                        msg = "解压完成但未找到 index.mjs，请确认资产为官方 SnowLuma 发行包"
                        raise RuntimeError(msg)

                    self._extract_root.mkdir(parents=True, exist_ok=True)
                    tag_written = resolved_tag_for_manifest or self._job_tag or release_tag
                    tw = (str(tag_written).strip() if tag_written is not None else "") or "latest"
                    slug = sanitize_release_tag_for_path(tw)
                    final_root = self._extract_root / slug
                    if await asyncio.to_thread(final_root.exists):
                        shutil.rmtree(final_root, ignore_errors=True)
                    await asyncio.to_thread(shutil.move, str(stage), str(final_root))

                    program_dir = find_snowluma_program_dir(final_root)
                    if program_dir is None:
                        msg = "解压目录异常：未找到 index.mjs"
                        raise RuntimeError(msg)

                    manifest = RuntimeManifest(
                        program_dir=str(program_dir.resolve()),
                        extract_root=str(final_root.resolve()),
                        asset_name=asset_name,
                        release_tag=tw,
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

    def start_background_download(
        self,
        *,
        tag: str | None = None,
        target_platform: str | None = None,
        on_success: Callable[[], None] | None = None,
    ) -> None:
        if self.is_busy():
            msg = "已有 SnowLuma 下载或解压任务在执行"
            raise RuntimeError(msg)
        self._job_tag = tag.strip() if tag and tag.strip() else self._release_tag()

        async def _run() -> None:
            try:
                await self.download_and_install(tag=tag, target_platform=target_platform)
                if on_success is not None:
                    on_success()
            except Exception as e:
                self._set_job("error", str(e))

        self._job_task = asyncio.create_task(_run())

    def _safe_extract_child_folder(self, folder_name: str) -> Path:
        raw = (folder_name or "").strip()
        if not raw or ".." in raw.replace("\\", "/"):
            raise ValueError("无效的解压目录名")
        safe = raw.replace("\\", "/").split("/")[-1]
        if not safe or safe in (".", ".."):
            raise ValueError("无效的解压目录名")
        folder = (self._extract_root / safe).resolve()
        eroot = self._extract_root.resolve()
        if folder.parent != eroot:
            raise ValueError("仅能选择解压根目录下的一级子目录")
        return folder

    def list_local_inventory(self) -> dict[str, Any]:
        """列出 ``runtime_dist`` 与 ``runtime_extract`` 下的本机缓存。"""
        dist_files: list[dict[str, Any]] = []
        if self._dist_dir.is_dir():
            for p in sorted(self._dist_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                if not p.is_file():
                    continue
                st = p.stat()
                dist_files.append({
                    "name": p.name,
                    "size_bytes": st.st_size,
                    "mtime_iso": datetime.fromtimestamp(st.st_mtime, tz=UTC).isoformat(),
                })
        extract_dirs: list[dict[str, Any]] = []
        cur = ""
        m = self.read_manifest()
        if m and m.extract_root:
            cur = str(Path(m.extract_root).resolve())
        if self._extract_root.is_dir():
            for p in sorted(self._extract_root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                if not p.is_dir():
                    continue
                st = p.stat()
                pr = str(p.resolve())
                extract_dirs.append({
                    "name": p.name,
                    "mtime_iso": datetime.fromtimestamp(st.st_mtime, tz=UTC).isoformat(),
                    "is_active": bool(cur and pr == cur),
                })
        return {"dist_files": dist_files, "extract_dirs": extract_dirs}

    def resolve_program_dir_for_tag_slug(self, slug: str) -> Path | None:
        safe = sanitize_release_tag_for_path(slug)
        folder = (self._extract_root / safe).resolve()
        eroot = self._extract_root.resolve()
        if folder.parent != eroot or not folder.is_dir():
            return None
        hit = find_snowluma_program_dir(folder)
        return hit.resolve() if hit else None

    def activate_extract_by_tag(self, tag: str) -> RuntimeManifest:
        raw = (tag or "").strip()
        if not raw:
            raise ValueError("缺少版本标签")
        slug = sanitize_release_tag_for_path(raw)
        folder = self._safe_extract_child_folder(slug)
        if not folder.is_dir():
            raise ValueError(f"未找到该版本的解压目录（请先下载对应 Release）：{slug}")
        program_dir = find_snowluma_program_dir(folder)
        if program_dir is None:
            raise ValueError("该目录中未找到 SnowLuma 发行根（index.mjs）")
        prev = self.read_manifest()
        manifest = RuntimeManifest(
            program_dir=str(program_dir.resolve()),
            extract_root=str(folder.resolve()),
            asset_name=(prev.asset_name if prev and prev.asset_name else ""),
            release_tag=raw,
            source_url=(prev.source_url if prev else ""),
        )
        self._manifest_path.write_text(
            json.dumps(manifest.to_json(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._set_job("done", f"已切换到版本 {raw}: {manifest.program_dir}")
        return manifest

    def activate_extract_folder(self, folder_name: str) -> RuntimeManifest:
        """将 manifest 指向已有解压子目录。"""
        folder = self._safe_extract_child_folder(folder_name)
        if not folder.is_dir():
            raise ValueError("解压目录不存在")
        program_dir = find_snowluma_program_dir(folder)
        if program_dir is None:
            raise ValueError("该目录中未找到 SnowLuma 发行根（index.mjs）")
        prev = self.read_manifest()
        manifest = RuntimeManifest(
            program_dir=str(program_dir.resolve()),
            extract_root=str(folder.resolve()),
            asset_name=(prev.asset_name if prev and prev.asset_name else ""),
            release_tag=f"local:{folder.name}",
            source_url=(prev.source_url if prev else ""),
        )
        self._manifest_path.write_text(
            json.dumps(manifest.to_json(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._set_job("done", f"已切换到本地解压: {manifest.program_dir}")
        return manifest

    async def fetch_releases(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """获取 SnowLuma 仓库的 release 列表。"""
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"User-Agent": "Pallas-Bot-PallasProtocol/1.0"},
        ) as client:
            return await fetch_github_releases(self._repo(), client=client, limit=limit, token=self._github_token())
