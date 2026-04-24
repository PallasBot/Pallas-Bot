"""NapCat 运行时下载与安装（Shell zip / Linux AppImage）。"""

from __future__ import annotations

import asyncio
import json
import os
import platform as py_platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from stat import S_IXGRP, S_IXOTH, S_IXUSR
from typing import Any, Literal
from urllib.parse import quote

import httpx

JobStatus = Literal["idle", "downloading", "extracting", "installing", "done", "error"]

# 官方一键流程：解压后运行 NapCatInstaller.exe，生成 NapCat.*.Shell；见
# https://napneko.github.io/guide/boot/Shell
_INSTALLER_TIMEOUT_SEC = 7200


def _github_release_asset_url(repo: str, asset_name: str, tag: str = "") -> str:
    owner_part, _, name_part = repo.partition("/")
    if not owner_part or not name_part:
        msg = f"无效的 GitHub 仓库名: {repo!r}，应为 Owner/Repo"
        raise ValueError(msg)
    encoded = quote(asset_name, safe=".")
    if not tag.strip():
        return f"https://github.com/{owner_part}/{name_part}/releases/latest/download/{encoded}"
    return f"https://github.com/{owner_part}/{name_part}/releases/download/{tag.strip()}/{encoded}"


def _github_release_api_url(repo: str, tag: str = "") -> str:
    owner_part, _, name_part = repo.partition("/")
    if not owner_part or not name_part:
        msg = f"无效的 GitHub 仓库名: {repo!r}，应为 Owner/Repo"
        raise ValueError(msg)
    if not tag.strip():
        return f"https://api.github.com/repos/{owner_part}/{name_part}/releases/latest"
    return f"https://api.github.com/repos/{owner_part}/{name_part}/releases/tags/{tag.strip()}"


def _arch_tokens_from_asset_name(asset_name: str) -> tuple[str, ...]:
    n = asset_name.lower()
    if "arm64" in n or "aarch64" in n:
        return ("arm64", "aarch64")
    if "amd64" in n or "x86_64" in n:
        return ("amd64", "x86_64")
    return ()


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
    """定位官方一键包安装完成后的目录（``NapCat.*.Shell`` 下的 ``bootmain`` 或含 mjs 的根）。"""
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
    exe = extract_root / "NapCatInstaller.exe"
    if not exe.is_file():
        return None
    completed = subprocess.run(
        [str(exe)],
        cwd=str(extract_root),
        timeout=timeout_sec,
        check=False,
    )
    return int(completed.returncode)


def find_napcat_program_dir(
    search_root: Path,
    *,
    max_depth: int = 8,
    prefer_bootmain: bool = False,
) -> Path | None:
    """在解压目录中定位「可启动」目录。

    - NapCat.Shell.zip：以 napcat.mjs 为准（与 napcat-shell-loader 的 launcher 一致）。
    - OneKey.zip：安装完成后应优先用 :func:`find_onekey_post_install_program_dir`；
      本函数在无 ``NapCat.*.Shell`` 时作浅层回退（例如无安装器的旧布局）。
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
        self._dist_dir = self._data_dir / "runtime_dist"
        self._extract_root = self._data_dir / "runtime_extract"
        self._manifest_path = self._data_dir / "runtime_manifest.json"
        self._lock = asyncio.Lock()
        self._job_status: JobStatus = "idle"
        self._job_message = ""
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
        return {"status": self._job_status, "message": self._job_message}

    def is_busy(self) -> bool:
        return self._job_status in ("downloading", "extracting", "installing")

    def _repo(self) -> str:
        configured = str(getattr(self._config, "pallas_protocol_github_repo", "")).strip()
        return configured or default_release_repo_for_platform()

    def _asset_name(self) -> str:
        fn = getattr(self._config, "resolved_release_asset", None)
        if callable(fn):
            return str(fn()).strip()
        return str(getattr(self._config, "pallas_protocol_release_asset", "")).strip()

    def _release_tag(self) -> str:
        return str(getattr(self._config, "pallas_protocol_release_tag", "")).strip()

    async def download_and_install(self, *, client: httpx.AsyncClient | None = None) -> RuntimeManifest:
        async with self._lock:
            asset_name = self._asset_name()
            if not asset_name:
                msg = "未配置 pallas_protocol_release_asset，无法下载"
                raise ValueError(msg)
            self._set_job("downloading", "准备下载…")
            repo = self._repo()
            release_tag = self._release_tag()
            url = _github_release_asset_url(repo, asset_name, release_tag)
            self._dist_dir.mkdir(parents=True, exist_ok=True)
            dist_file = self._dist_dir / asset_name

            own_client = client is None
            hc = client or httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(600.0, connect=30.0),
                headers={"User-Agent": "Pallas-Bot-PallasProtocol/1.0"},
            )
            try:
                if asset_is_linux_appimage(asset_name):
                    rel_api = _github_release_api_url(repo, release_tag)
                    rel_resp = await hc.get(rel_api)
                    if rel_resp.status_code == 200:
                        pick = _pick_appimage_asset_from_release(rel_resp.json(), asset_name)
                        if pick is not None:
                            asset_name, url = pick
                            dist_file = self._dist_dir / asset_name
                async with hc.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        msg = f"下载失败 HTTP {resp.status_code}: {url}"
                        raise RuntimeError(msg)
                    total = int(resp.headers.get("content-length") or 0)
                    received = 0
                    with dist_file.open("wb") as out:
                        async for chunk in resp.aiter_bytes(1024 * 256):
                            if not chunk:
                                continue
                            out.write(chunk)
                            received += len(chunk)
                            if total > 0:
                                pct = min(99, int(received * 100 / total))
                                self._set_job("downloading", f"下载中 {pct}% ({received // (1024 * 1024)} MiB)")
                            else:
                                self._set_job("downloading", f"下载中… ({received // (1024 * 1024)} MiB)")
            finally:
                if own_client:
                    await hc.aclose()

            self._set_job("extracting", "安装中…")
            stage = Path(tempfile.mkdtemp(prefix="napcat_extract_", dir=str(self._data_dir)))
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
                final_root = self._extract_root / datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
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
                    release_tag=self._release_tag(),
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

    def start_background_download(self) -> None:
        if self.is_busy():
            msg = "已有下载或解压任务在执行"
            raise RuntimeError(msg)

        async def _run() -> None:
            try:
                await self.download_and_install()
            except Exception as e:
                self._set_job("error", str(e))

        self._job_task = asyncio.create_task(_run())

    def _set_job(self, status: JobStatus, message: str) -> None:
        self._job_status = status
        self._job_message = message

    def rescan_existing_extract(self) -> RuntimeManifest | None:
        """不重新下载，仅在已有解压目录中查找 Shell 根（用于一键包安装器生成子目录后）。"""
        if not self._extract_root.exists():
            return None
        candidates = sorted(self._extract_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        prefer_boot = asset_is_windows_onekey(self._asset_name())
        prefer_appimage = asset_is_linux_appimage(self._asset_name())
        for folder in candidates:
            if not folder.is_dir():
                continue
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
            if program_dir is None:
                continue
            url = _github_release_asset_url(self._repo(), self._asset_name(), self._release_tag())
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


# NapNeko/NapCatQQ releases：Windows 为显式包名；Linux/macOS/其他类 Unix 为无 Windows 前缀的通用 Shell
_NC_ASSET_WINDOWS_ONEKEY = "NapCat.Shell.Windows.OneKey.zip"
_NC_ASSET_SHELL_GENERIC = "NapCat.Shell.zip"
_NC_REPO_SHELL = "NapNeko/NapCatQQ"
_NC_REPO_APPIMAGE = "NapNeko/NapCatAppImageBuild"
_NC_APPIMAGE_X64 = "QQ-x86_64.AppImage"
_NC_APPIMAGE_AARCH64 = "QQ-aarch64.AppImage"


def default_release_repo_for_platform() -> str:
    if sys.platform.startswith("linux"):
        return _NC_REPO_APPIMAGE
    return _NC_REPO_SHELL


def default_release_asset_for_platform() -> str:
    """按平台选择默认 release 资产名（空配置时 `resolved_release_asset` 会调用）。

    - Windows：NapCatQQ 一键包 zip
    - Linux：NapCatAppImageBuild 的 AppImage（按架构）
    - 其它 POSIX：保留 NapCat.Shell.zip
    """
    if sys.platform == "win32":
        return _NC_ASSET_WINDOWS_ONEKEY
    if sys.platform.startswith("linux"):
        machine = (py_platform.machine() or "").lower()
        return _NC_APPIMAGE_AARCH64 if machine in ("aarch64", "arm64") else _NC_APPIMAGE_X64
    return _NC_ASSET_SHELL_GENERIC
