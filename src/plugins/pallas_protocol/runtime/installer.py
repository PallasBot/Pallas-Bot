"""NapCat 运行时下载与安装。"""

from __future__ import annotations

import asyncio
import json
import os
import platform as py_platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from stat import S_IXGRP, S_IXOTH, S_IXUSR
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Callable
from urllib.parse import urlparse

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

from .tag_paths import sanitize_release_tag_for_path

JobStatus = Literal["idle", "downloading", "extracting", "installing", "done", "error"]

# 一键安装超时秒数
_INSTALLER_TIMEOUT_SEC = 7200


def unlink_files_in_dir(path: Path) -> int:
    """删除目录下的普通文件，不删除子目录。"""
    n = 0
    if not path.is_dir():
        return 0
    for child in path.iterdir():
        if child.is_file():
            try:
                child.unlink()
                n += 1
            except OSError:
                pass
    return n


def _looks_like_http_url(value: str) -> bool:
    s = (value or "").strip()
    return s.startswith(("http://", "https://"))


def _asset_name_from_url(value: str) -> str:
    parsed = urlparse(value)
    return Path(parsed.path).name.strip()


def _arch_tokens_from_asset_name(asset_name: str) -> tuple[str, ...]:
    n = asset_name.lower()
    if "arm64" in n or "aarch64" in n:
        return ("arm64", "aarch64")
    if "amd64" in n or "x86_64" in n:
        return ("amd64", "x86_64")
    return ()


def _asset_ext(asset_name: str) -> str:
    return Path((asset_name or "").strip()).suffix.lower()


def _pick_release_asset_generic(
    release_json: dict[str, Any],
    preferred_asset: str,
) -> tuple[str, str] | None:
    assets = release_json.get("assets")
    if not isinstance(assets, list):
        return None
    entries: list[tuple[str, str]] = []
    by_name: dict[str, str] = {}
    for item in assets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        url = str(item.get("browser_download_url", "")).strip()
        if not name or not url:
            continue
        entries.append((name, url))
        by_name[name] = url
    if preferred_asset in by_name:
        return preferred_asset, by_name[preferred_asset]
    if not entries:
        return None
    pref_ext = _asset_ext(preferred_asset)
    arch_tokens = _arch_tokens_from_asset_name(preferred_asset)
    if pref_ext:
        by_ext = [(n, u) for n, u in entries if n.lower().endswith(pref_ext)]
    else:
        by_ext = entries
    if arch_tokens:
        for name, url in by_ext:
            low = name.lower()
            if any(tok in low for tok in arch_tokens):
                return name, url
    if by_ext:
        return by_ext[0]
    return entries[0]


def _pick_appimage_asset_from_release(release_json: dict[str, Any], preferred_asset: str) -> tuple[str, str] | None:
    assets = release_json.get("assets")
    if not isinstance(assets, list):
        return None
    by_name: dict[str, str] = {}
    for item in assets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        url = str(item.get("browser_download_url", "")).strip()
        if not name or not url or not name.endswith(".AppImage"):
            continue
        by_name[name] = url
    if preferred_asset in by_name:
        return preferred_asset, by_name[preferred_asset]
    arch_tokens = _arch_tokens_from_asset_name(preferred_asset)
    if arch_tokens:
        for name, url in by_name.items():
            low = name.lower()
            if any(tok in low for tok in arch_tokens):
                return name, url
    for name, url in by_name.items():
        return name, url
    return None


def _pick_appimage_asset_from_release_html(html: str, repo: str, preferred_asset: str) -> tuple[str, str] | None:
    if not html.strip():
        return None
    owner_part, _, name_part = repo.partition("/")
    if not owner_part or not name_part:
        return None
    base = f"/{owner_part}/{name_part}/releases/download/"
    hits = re.findall(r'href="([^"]+\.AppImage)"', html)
    assets: dict[str, str] = {}
    for href in hits:
        if base not in href:
            continue
        full = f"https://github.com{href}" if href.startswith("/") else href
        name = full.rsplit("/", 1)[-1]
        assets[name] = full
    if preferred_asset in assets:
        return preferred_asset, assets[preferred_asset]
    arch_tokens = _arch_tokens_from_asset_name(preferred_asset)
    if arch_tokens:
        for name, url in assets.items():
            low = name.lower()
            if any(tok in low for tok in arch_tokens):
                return name, url
    for name, url in assets.items():
        return name, url
    return None


def _safe_extract_zip(zip_path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            name = member.filename
            if name.startswith("/") or ".." in Path(name).parts:
                msg = f"非法 zip 条目: {name!r}"
                raise ValueError(msg)
            target = (dest_dir / name).resolve()
            if not str(target).startswith(str(dest_dir.resolve())):
                msg = f"非法 zip 路径: {name!r}"
                raise ValueError(msg)
        zf.extractall(dest_dir)


def asset_is_windows_onekey(asset_name: str) -> bool:
    return "OneKey" in asset_name


def asset_is_linux_appimage(asset_name: str) -> bool:
    return asset_name.strip().endswith(".AppImage")


def find_appimage_under_dir(search_root: Path) -> Path | None:
    root = search_root.resolve()
    if not root.is_dir():
        return None
    cands = [p for p in root.rglob("*.AppImage") if p.is_file()]
    if not cands:
        return None
    cands.sort(key=lambda p: (len(p.relative_to(root).parts), -p.stat().st_mtime))
    return cands[0]


def find_onekey_post_install_program_dir(search_root: Path) -> Path | None:
    """定位官方一键包安装完成后的目录。"""
    root = search_root.resolve()
    if not root.is_dir():
        return None
    shell_dirs = [
        p for p in root.iterdir() if p.is_dir() and p.name.startswith("NapCat.") and p.name.endswith(".Shell")
    ]
    shell_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for shell in shell_dirs:
        boot_main = shell / "bootmain" / "NapCatWinBootMain.exe"
        if boot_main.is_file():
            return shell / "bootmain"
        if (shell / "NapCatWinBootMain.exe").is_file():
            return shell
        if (shell / "napcat.mjs").is_file():
            return shell
    return None


def resolve_program_dir_under_extract(search_root: Path, *, onekey: bool) -> Path | None:
    """在解压根目录下解析 program_dir；一键包在存在 NapCatInstaller.exe 且未完成 Shell 布局时不误选根级 bootmain。"""
    root = search_root.resolve()
    if not root.is_dir():
        return None
    if onekey:
        hit = find_onekey_post_install_program_dir(root)
        if hit is not None:
            return hit
        if (root / "NapCatInstaller.exe").is_file():
            return None
    return find_napcat_program_dir(root, prefer_bootmain=onekey)


def _run_napcat_installer_sync(extract_root: Path, *, timeout_sec: int = _INSTALLER_TIMEOUT_SEC) -> int | None:
    """Windows 下一键包官方步骤：运行解压根目录的 NapCatInstaller.exe；未找到则跳过。"""
    if os.name != "nt":
        return None
    root = extract_root.resolve()
    exe = (root / "NapCatInstaller.exe").resolve()
    if not exe.is_file():
        return None
    # 仅允许执行当前解压目录内的官方安装器，避免路径被外部输入污染。
    if not str(exe).startswith(str(root) + os.sep):
        msg = f"检测到异常安装器路径: {exe}"
        raise RuntimeError(msg)
    # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
    completed = subprocess.run(
        [str(exe)],
        cwd=str(root),
        timeout=timeout_sec,
        check=False,
        shell=False,
    )
    return int(completed.returncode)


def find_napcat_program_dir(
    search_root: Path,
    *,
    max_depth: int = 8,
    prefer_bootmain: bool = False,
) -> Path | None:
    """在解压目录中定位「可启动」目录。

    - NapCat.Shell.zip：以 napcat.mjs 为准。
    - OneKey.zip：安装完成后应优先用 :func:`find_onekey_post_install_program_dir`
      本函数在无 ``NapCat.*.Shell`` 时作浅层回退。
    """
    root = search_root.resolve()
    if not root.exists():
        return None

    def depth(p: Path) -> int:
        try:
            return len(p.relative_to(root).parts)
        except ValueError:
            return 999

    def best_parent_for_filename(filename: str) -> Path | None:
        best: Path | None = None
        best_rank = 999
        for path in root.rglob(filename):
            if not path.is_file():
                continue
            if depth(path) > max_depth:
                continue
            parent = path.parent
            rank = depth(parent)
            if rank < best_rank:
                best_rank = rank
                best = parent
        return best

    if prefer_bootmain:
        boot = best_parent_for_filename("NapCatWinBootMain.exe")
        if boot is not None:
            return boot
        return best_parent_for_filename("napcat.mjs")

    mjs_dir = best_parent_for_filename("napcat.mjs")
    if mjs_dir is not None:
        return mjs_dir
    return best_parent_for_filename("NapCatWinBootMain.exe")


@dataclass
class RuntimeManifest:
    program_dir: str
    extract_root: str
    asset_name: str
    release_tag: str
    source_url: str
    downloaded_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_json(self) -> dict[str, Any]:
        return {
            "program_dir": self.program_dir,
            "extract_root": self.extract_root,
            "asset_name": self.asset_name,
            "release_tag": self.release_tag,
            "source_url": self.source_url,
            "downloaded_at": self.downloaded_at,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> RuntimeManifest | None:
        try:
            return cls(
                program_dir=str(data["program_dir"]),
                extract_root=str(data["extract_root"]),
                asset_name=str(data["asset_name"]),
                release_tag=str(data.get("release_tag", "")),
                source_url=str(data.get("source_url", "")),
                downloaded_at=str(data.get("downloaded_at", "")),
            )
        except (KeyError, TypeError):
            return None


class NapCatRuntimeStore:
    """管理插件数据目录下的 NapCat Shell 分发包。"""

    def __init__(self, data_dir: Path, config: Any) -> None:
        self._data_dir = data_dir
        self._config = config
        self._dist_dir = self._data_dir / "runtime_dist" / "napcat"
        self._extract_root = self._data_dir / "runtime_extract" / "napcat"
        self._manifest_path = self._data_dir / "runtime_manifest.json"
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

    def clear_manifest(self) -> None:
        if self._manifest_path.exists():
            self._manifest_path.unlink()

    def clear_dist_file_cache(self) -> int:
        """删除已下载的发行包文件，不删 runtime_extract 与 manifest。"""
        return unlink_files_in_dir(self._dist_dir)

    def resolved_program_dir(self) -> Path | None:
        m = self.read_manifest()
        if not m:
            return None
        prog = Path(m.program_dir)
        extract = Path(m.extract_root)
        onekey = asset_is_windows_onekey(m.asset_name)
        appimage = asset_is_linux_appimage(m.asset_name)

        def usable(d: Path) -> bool:
            if d.is_dir() and ((d / "NapCatWinBootMain.exe").is_file() or (d / "napcat.mjs").is_file()):
                return True
            if d.is_file() and d.suffix == ".AppImage":
                return True
            if d.is_dir() and find_appimage_under_dir(d) is not None:
                return True
            return False

        if usable(prog):
            if onekey and extract.is_dir():
                shell_hit = find_onekey_post_install_program_dir(extract)
                if shell_hit is not None and shell_hit.resolve() != prog.resolve():
                    data = m.to_json()
                    data["program_dir"] = str(shell_hit.resolve())
                    self._manifest_path.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    return shell_hit
            return prog
        if extract.is_dir():
            if appimage:
                hit = find_appimage_under_dir(extract)
                if hit is not None:
                    if hit.resolve() != prog.resolve():
                        data = m.to_json()
                        data["program_dir"] = str(hit.resolve())
                        self._manifest_path.write_text(
                            json.dumps(data, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                    return hit
            found = resolve_program_dir_under_extract(extract, onekey=onekey)
            if found and usable(found):
                if found.resolve() != prog.resolve():
                    data = m.to_json()
                    data["program_dir"] = str(found.resolve())
                    self._manifest_path.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                return found
        return prog if usable(prog) else None

    def job_snapshot(self) -> dict[str, Any]:
        return {"status": self._job_status, "message": self._job_message, "tag": self._job_tag}

    def is_busy(self) -> bool:
        return self._job_status in ("downloading", "extracting", "installing")

    def _github_token(self) -> str:
        return str(getattr(self._config, "pallas_protocol_github_token", "") or "").strip()

    def _repo(self, target_platform: str = "auto") -> str:
        configured = str(getattr(self._config, "pallas_protocol_github_repo", "")).strip()
        if not configured:
            return default_release_repo_for_platform(target_platform)
        if (target_platform or "auto").strip().lower() != "auto":
            auto_default = default_release_repo_for_platform("auto")
            if configured == auto_default:
                return default_release_repo_for_platform(target_platform)
        return configured

    def _repo_candidates(self, target_platform: str = "auto") -> list[str]:
        """Linux 下自动尝试多个来源，减少因单仓库命名变化导致的硬编码配置。"""
        primary = self._repo(target_platform)
        out: list[str] = [primary]
        if target_platform.startswith("linux") or (target_platform == "auto" and sys.platform.startswith("linux")):
            for repo in (_NC_REPO_APPIMAGE, _NC_REPO_SHELL):
                if repo not in out:
                    out.append(repo)
        return out

    def _asset_name(self, target_platform: str = "auto") -> str:
        fn = getattr(self._config, "resolved_release_asset", None)
        if callable(fn):
            val = str(fn()).strip()
        else:
            val = str(getattr(self._config, "pallas_protocol_release_asset", "")).strip()
        if val.lower() in ("auto", "latest"):
            return ""
        if (target_platform or "auto").strip().lower() != "auto":
            auto_default = default_release_asset_for_platform()
            if val == auto_default:
                return default_release_asset_for_platform(target_platform=target_platform)
        return val

    def _release_tag(self) -> str:
        return str(getattr(self._config, "pallas_protocol_release_tag", "")).strip()

    def _on_stream_download_progress(self, ev: StreamDownloadProgress) -> None:
        if ev["event"] == "percent":
            self._set_job(
                "downloading",
                f"下载中 {ev['milestone_percent']}% "
                f"({format_download_byte_size(ev['received'])}/{format_download_byte_size(ev['total'])})",
            )
        elif ev["event"] == "complete":
            self._set_job("downloading", "下载完成，准备解压…")
        elif ev["event"] == "unknown_step":
            self._set_job(
                "downloading",
                f"下载中… ({format_download_byte_size(ev['received'])})",
            )

    async def download_and_install(
        self, *, client: httpx.AsyncClient | None = None, tag: str | None = None, target_platform: str = "auto"
    ) -> RuntimeManifest:
        async with self._lock:
            configured_asset = self._asset_name(target_platform)
            release_tag = tag.strip() if tag and tag.strip() else self._release_tag()
            self._job_tag = release_tag
            if not configured_asset:
                configured_asset = default_release_asset_for_platform(release_tag, target_platform=target_platform)
            direct_asset_url = configured_asset if _looks_like_http_url(configured_asset) else ""
            asset_name = _asset_name_from_url(direct_asset_url) if direct_asset_url else configured_asset
            if not asset_name:
                msg = "未解析到可下载资产名，请检查 pallas_protocol_release_asset"
                raise ValueError(msg)
            self._set_job("downloading", "准备下载…")
            repo = self._repo(target_platform)
            url = direct_asset_url or github_release_asset_url(repo, asset_name, release_tag)
            self._dist_dir.mkdir(parents=True, exist_ok=True)
            dist_file = self._dist_dir / asset_name

            github_token = self._github_token()
            own_client = client is None
            hc = client or httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(600.0, connect=30.0),
                headers={"User-Agent": "Pallas-Bot-PallasProtocol/1.0"},
            )
            try:
                download_candidates: list[tuple[str, str, str]] = []
                if direct_asset_url:
                    download_candidates.append((repo, asset_name, url))
                else:
                    tag_candidates = [release_tag] if release_tag else [""]
                    if release_tag:
                        tag_candidates.append("")
                    _gh_headers = github_auth_headers(github_token)
                    for repo_try in self._repo_candidates(target_platform):
                        for tag_try in tag_candidates:
                            rel_api = github_release_api_url(repo_try, tag_try)
                            rel_resp = await hc.get(rel_api, headers=_gh_headers)
                            if rel_resp.status_code == 200:
                                pick = _pick_release_asset_generic(rel_resp.json(), asset_name)
                                if pick is not None:
                                    pick_name, pick_url = pick
                                    download_candidates.append((repo_try, pick_name, pick_url))
                                    continue
                            if asset_is_linux_appimage(asset_name) and rel_resp.status_code in (403, 404, 429):
                                # 解析发布页资产
                                rel_web = (
                                    f"https://github.com/{repo_try}/releases/latest"
                                    if not tag_try.strip()
                                    else f"https://github.com/{repo_try}/releases/tag/{tag_try.strip()}"
                                )
                                web_resp = await hc.get(rel_web)
                                if web_resp.status_code == 200:
                                    pick = _pick_appimage_asset_from_release_html(web_resp.text, repo_try, asset_name)
                                    if pick is not None:
                                        pick_name, pick_url = pick
                                        download_candidates.append((repo_try, pick_name, pick_url))
                    if not download_candidates:
                        # 添加直链候选
                        download_candidates.append((
                            repo,
                            asset_name,
                            github_release_asset_url(repo, asset_name, release_tag),
                        ))

                errors: list[str] = []
                deduped: list[tuple[str, str, str]] = []
                seen: set[str] = set()
                for cand in download_candidates:
                    sig = f"{cand[0]}|{cand[1]}|{cand[2]}"
                    if sig in seen:
                        continue
                    seen.add(sig)
                    deduped.append(cand)

                download_headers: dict[str, str] = {
                    "User-Agent": "Pallas-Bot-PallasProtocol/1.0",
                    **github_auth_headers(github_token),
                }

                success = False
                for repo_try, name_try, url_try in deduped:
                    cand_dist = self._dist_dir / name_try
                    try:
                        await asyncio.to_thread(
                            sync_stream_download_to_file,
                            url_try,
                            cand_dist,
                            follow_redirects=True,
                            timeout=httpx.Timeout(600.0, connect=30.0),
                            headers=download_headers,
                            on_progress=self._on_stream_download_progress,
                        )
                    except httpx.HTTPStatusError as e:
                        code = e.response.status_code if e.response is not None else "?"
                        errors.append(f"{name_try} @ {repo_try} -> HTTP {code}")
                        continue
                    repo = repo_try
                    asset_name = name_try
                    url = url_try
                    dist_file = cand_dist
                    success = True
                    break
                if not success:
                    msg = f"下载失败，候选均不可用: {' | '.join(errors)}"
                    raise RuntimeError(msg)
            finally:
                if own_client:
                    await hc.aclose()

            self._set_job("extracting", "安装中…")
            self._extract_root.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix="napcat_extract_", dir=str(self._extract_root)))
            try:
                is_appimage = asset_is_linux_appimage(asset_name)
                if is_appimage:
                    app_dst = stage / asset_name
                    await asyncio.to_thread(shutil.copy2, dist_file, app_dst)
                    mode = app_dst.stat().st_mode
                    app_dst.chmod(mode | S_IXUSR | S_IXGRP | S_IXOTH)
                else:
                    await asyncio.to_thread(_safe_extract_zip, dist_file, stage)
                prefer_boot = asset_is_windows_onekey(asset_name)
                if is_appimage:
                    if find_appimage_under_dir(stage) is None:
                        msg = "下载完成但未找到 AppImage 文件，请确认 release 资产名与内容。"
                        raise RuntimeError(msg)
                elif prefer_boot:
                    has_marker = (
                        (stage / "NapCatInstaller.exe").is_file()
                        or find_napcat_program_dir(stage, prefer_bootmain=True) is not None
                        or find_napcat_program_dir(stage, prefer_bootmain=False) is not None
                    )
                    if not has_marker:
                        msg = "一键包解压后未找到 NapCatInstaller.exe 或任何可启动文件。请确认 zip 完整。"
                        raise RuntimeError(msg)
                else:
                    if find_napcat_program_dir(stage, prefer_bootmain=False) is None:
                        msg = "解压完成但未找到 napcat.mjs，请确认为标准 NapCat.Shell.zip"
                        raise RuntimeError(msg)

                self._extract_root.mkdir(parents=True, exist_ok=True)
                tag_for_dir = release_tag.strip() or "latest"
                slug = sanitize_release_tag_for_path(tag_for_dir)
                final_root = self._extract_root / slug
                if await asyncio.to_thread(final_root.exists):
                    shutil.rmtree(final_root, ignore_errors=True)
                await asyncio.to_thread(shutil.move, str(stage), str(final_root))

                if prefer_boot and (final_root / "NapCatInstaller.exe").is_file():
                    self._set_job(
                        "installing",
                        "运行 NapCatInstaller.exe（官方一键部署，可能较久）…",
                    )
                    try:
                        rc = await asyncio.to_thread(_run_napcat_installer_sync, final_root)
                    except subprocess.TimeoutExpired as e:
                        msg = (
                            f"NapCatInstaller.exe 超过 {_INSTALLER_TIMEOUT_SEC}s 仍未结束。"
                            "请在本机手动运行解压目录中的安装器，完成后点「刷新检测」。"
                        )
                        raise RuntimeError(msg) from e
                    if rc != 0 and find_onekey_post_install_program_dir(final_root) is None:
                        msg = (
                            f"NapCatInstaller.exe 退出码 {rc}，且未生成 NapCat.*.Shell。"
                            "请查看安装器界面提示后重试，或手动安装后「刷新检测」。"
                            "文档: https://napneko.github.io/guide/boot/Shell"
                        )
                        raise RuntimeError(msg)

                if is_appimage:
                    program_dir = find_appimage_under_dir(final_root)
                else:
                    program_dir = resolve_program_dir_under_extract(final_root, onekey=prefer_boot)
                    if program_dir is None and prefer_boot and not (final_root / "NapCatInstaller.exe").is_file():
                        program_dir = find_napcat_program_dir(final_root, prefer_bootmain=prefer_boot)
                if program_dir is None:
                    if is_appimage:
                        msg = "未找到可执行 AppImage 文件。"
                    else:
                        msg = (
                            "未找到可启动目录。"
                            "一键包请确认 NapCatInstaller.exe 已成功生成 NapCat.*.Shell 目录；"
                            "亦可手动运行安装器后点「刷新检测」。"
                            "说明见 https://napneko.github.io/guide/boot/Shell"
                        )
                    raise RuntimeError(msg)

                manifest = RuntimeManifest(
                    program_dir=str(program_dir.resolve()),
                    extract_root=str(final_root.resolve()),
                    asset_name=asset_name,
                    release_tag=(release_tag.strip() or "latest"),
                    source_url=url,
                )
                self._manifest_path.write_text(
                    json.dumps(manifest.to_json(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                self._set_job("done", f"安装完成: {manifest.program_dir}")
                return manifest
            except Exception:
                shutil.rmtree(stage, ignore_errors=True)
                raise
            finally:
                if await asyncio.to_thread(stage.exists):
                    shutil.rmtree(stage, ignore_errors=True)

    def start_background_download(
        self,
        *,
        tag: str | None = None,
        target_platform: str = "auto",
        on_success: Callable[[], None] | None = None,
    ) -> None:
        if self.is_busy():
            msg = "已有下载或解压任务在执行"
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

    def _set_job(self, status: JobStatus, message: str) -> None:
        self._job_status = status
        self._job_message = message

    async def fetch_releases(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """获取当前配置仓库的 release 列表，供前端展示 tag 选择。

        返回 ``[{tag, assets: [{name, url}]}]``，Windows 资产不含 tag 后缀，
        Linux AppImage 资产名含 tag 与架构，调用方可直接用于构造下载参数。
        """
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"User-Agent": "Pallas-Bot-PallasProtocol/1.0"},
        ) as client:
            return await fetch_github_releases(self._repo(), client=client, limit=limit, token=self._github_token())

    def _resolve_program_dir_in_extract_folder(self, folder: Path) -> Path | None:
        """在单个子目录中解析 NapCat 程序根。"""
        if not folder.is_dir():
            return None
        prefer_boot = asset_is_windows_onekey(self._asset_name())
        prefer_appimage = asset_is_linux_appimage(self._asset_name())
        program_dir = (
            find_appimage_under_dir(folder)
            if prefer_appimage
            else resolve_program_dir_under_extract(folder, onekey=prefer_boot)
        )
        if program_dir is None:
            program_dir = (
                find_napcat_program_dir(folder, prefer_bootmain=prefer_boot)
                if not prefer_boot or not (folder / "NapCatInstaller.exe").is_file()
                else None
            )
        return program_dir

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
        """解析 ``runtime_extract/napcat/<slug>`` 下的 NapCat 程序根。"""
        safe = sanitize_release_tag_for_path(slug)
        folder = (self._extract_root / safe).resolve()
        eroot = self._extract_root.resolve()
        if folder.parent != eroot or not folder.is_dir():
            return None
        hit = self._resolve_program_dir_in_extract_folder(folder)
        return hit.resolve() if hit else None

    def activate_extract_by_tag(self, tag: str) -> RuntimeManifest:
        """按 Release tag切换托管 manifest。"""
        raw = (tag or "").strip()
        if not raw:
            raise ValueError("缺少版本标签")
        slug = sanitize_release_tag_for_path(raw)
        folder = self._safe_extract_child_folder(slug)
        if not folder.is_dir():
            raise ValueError(f"未找到该版本的解压目录（请先下载对应 Release）：{slug}")
        program_dir = self._resolve_program_dir_in_extract_folder(folder)
        if program_dir is None:
            raise ValueError("该目录中未检测到可用的 NapCat 程序根")
        prev = self.read_manifest()
        manifest = RuntimeManifest(
            program_dir=str(program_dir.resolve()),
            extract_root=str(folder.resolve()),
            asset_name=(prev.asset_name if prev and prev.asset_name else self._asset_name()),
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
        program_dir = self._resolve_program_dir_in_extract_folder(folder)
        if program_dir is None:
            raise ValueError("该目录中未检测到可用的 NapCat 程序根")
        prev = self.read_manifest()
        manifest = RuntimeManifest(
            program_dir=str(program_dir.resolve()),
            extract_root=str(folder.resolve()),
            asset_name=(prev.asset_name if prev and prev.asset_name else self._asset_name()),
            release_tag=f"local:{folder.name}",
            source_url=(prev.source_url if prev else ""),
        )
        self._manifest_path.write_text(
            json.dumps(manifest.to_json(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._set_job("done", f"已切换到本地解压: {manifest.program_dir}")
        return manifest

    def rescan_existing_extract(self) -> RuntimeManifest | None:
        """不重新下载，仅在已有解压目录中查找 Shell 根。"""
        if not self._extract_root.exists():
            return None
        candidates = sorted(self._extract_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        for folder in candidates:
            if not folder.is_dir():
                continue
            program_dir = self._resolve_program_dir_in_extract_folder(folder)
            if program_dir is None:
                continue
            url = github_release_asset_url(self._repo(), self._asset_name(), self._release_tag())
            manifest = RuntimeManifest(
                program_dir=str(program_dir.resolve()),
                extract_root=str(folder.resolve()),
                asset_name=self._asset_name(),
                release_tag=self._release_tag(),
                source_url=url,
            )
            self._manifest_path.write_text(
                json.dumps(manifest.to_json(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._set_job("done", f"已检测到: {manifest.program_dir}")
            return manifest
        return None


# 默认发布资产名称
_NC_ASSET_WINDOWS_ONEKEY = "NapCat.Shell.Windows.OneKey.zip"
_NC_ASSET_SHELL_GENERIC = "NapCat.Shell.zip"
_NC_REPO_SHELL = "NapNeko/NapCatQQ"
_NC_REPO_APPIMAGE = "NapNeko/NapCatAppImageBuild"
# NapCatAppImageBuild 资产命名格式：QQ-{qq_ver}_NapCat-{tag}-{arch}.AppImage
# 使用 NapCat-{tag}-{arch}.AppImage 作为 preferred name，可精准命中 arch token 匹配
_NC_APPIMAGE_X64 = "NapCat-amd64.AppImage"
_NC_APPIMAGE_AARCH64 = "NapCat-arm64.AppImage"


def default_release_repo_for_platform(target_platform: str = "auto") -> str:
    tp = (target_platform or "auto").strip().lower()
    if tp.startswith("linux"):
        return _NC_REPO_APPIMAGE
    if tp.startswith("windows"):
        return _NC_REPO_SHELL
    if sys.platform.startswith("linux"):
        return _NC_REPO_APPIMAGE
    return _NC_REPO_SHELL


def default_release_asset_for_platform(tag: str = "", target_platform: str = "auto") -> str:
    """按平台选择默认 release 资产名（空配置时 `resolved_release_asset` 会调用）。

    - Windows：NapCatQQ 一键包 zip
    - Linux：NapCatAppImageBuild 的 AppImage；若提供 tag 则拼接为
      ``NapCat-{tag}-{arch}.AppImage``，与实际资产命名后缀对齐，提升命中率
    - 其它 POSIX：保留 NapCat.Shell.zip
    """
    tp = (target_platform or "auto").strip().lower()
    if tp == "windows-amd64":
        return _NC_ASSET_WINDOWS_ONEKEY
    if tp in ("linux-amd64", "linux-arm64"):
        arch = "arm64" if tp.endswith("arm64") else "amd64"
        if tag.strip():
            return f"NapCat-{tag.strip()}-{arch}.AppImage"
        return _NC_APPIMAGE_AARCH64 if arch == "arm64" else _NC_APPIMAGE_X64
    if sys.platform == "win32":
        return _NC_ASSET_WINDOWS_ONEKEY
    if sys.platform.startswith("linux"):
        machine = (py_platform.machine() or "").lower()
        arch = "arm64" if machine in ("aarch64", "arm64") else "amd64"
        if tag.strip():
            return f"NapCat-{tag.strip()}-{arch}.AppImage"
        return _NC_APPIMAGE_AARCH64 if arch == "arm64" else _NC_APPIMAGE_X64
    return _NC_ASSET_SHELL_GENERIC
