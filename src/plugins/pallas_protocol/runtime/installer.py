"""NapCat Shell 运行时的下载与解压（使用 GitHub releases 直链，避免 API 限流）。"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
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

        def usable(d: Path) -> bool:
            return d.is_dir() and ((d / "NapCatWinBootMain.exe").is_file() or (d / "napcat.mjs").is_file())

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
        return prog if prog.is_dir() else None

    def job_snapshot(self) -> dict[str, Any]:
        return {"status": self._job_status, "message": self._job_message}

    def is_busy(self) -> bool:
        return self._job_status in ("downloading", "extracting", "installing")

    def _repo(self) -> str:
        return str(getattr(self._config, "pallas_protocol_github_repo", "")).strip() or "NapNeko/NapCatQQ"

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
            url = _github_release_asset_url(self._repo(), asset_name, self._release_tag())
            self._dist_dir.mkdir(parents=True, exist_ok=True)
            dest_zip = self._dist_dir / asset_name

            own_client = client is None
            hc = client or httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(600.0, connect=30.0),
                headers={"User-Agent": "Pallas-Bot-PallasProtocol/1.0"},
            )
            try:
                async with hc.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        msg = f"下载失败 HTTP {resp.status_code}: {url}"
                        raise RuntimeError(msg)
                    total = int(resp.headers.get("content-length") or 0)
                    received = 0
                    with dest_zip.open("wb") as out:
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

            self._set_job("extracting", "解压中…")
            stage = Path(tempfile.mkdtemp(prefix="napcat_extract_", dir=str(self._data_dir)))
            try:
                await asyncio.to_thread(_safe_extract_zip, dest_zip, stage)
                prefer_boot = asset_is_windows_onekey(asset_name)
                if prefer_boot:
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

                program_dir = resolve_program_dir_under_extract(final_root, onekey=prefer_boot)
                if program_dir is None and prefer_boot and not (final_root / "NapCatInstaller.exe").is_file():
                    program_dir = find_napcat_program_dir(final_root, prefer_bootmain=prefer_boot)
                if program_dir is None:
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
        for folder in candidates:
            if not folder.is_dir():
                continue
            program_dir = resolve_program_dir_under_extract(folder, onekey=prefer_boot)
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


def default_release_asset_for_platform() -> str:
    """按 **当前运行 Python 的平台** 选择官方 Release 中的 zip 名（空配置时 `resolved_release_asset` 会调用本函数）。

    `NapNeko/NapCatQQ` 的 Asset 里并没有 ``NapCat.Shell.Linux.zip`` 这种单独命名；与 Windows 三件套并列、
    无 ``Windows`` 前缀的 ``NapCat.Shell.zip`` 即文档/发行中的 **Linux 与类 Unix 通用** Shell 包。Windows
    默认用一键包（会跑 ``NapCatInstaller.exe``）。若需 Win 的 Node 轻量包，请在配置中写
    ``NapCat.Shell.Windows.Node.zip`` 等显式值。
    """
    if sys.platform == "win32":
        return _NC_ASSET_WINDOWS_ONEKEY
    # linux / darwin / 其他 BSD、POSIX
    return _NC_ASSET_SHELL_GENERIC
