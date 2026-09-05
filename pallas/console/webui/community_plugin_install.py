"""社区插件安装到 local/plugins/（git clone）。"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from typing import TYPE_CHECKING

from nonebot import logger

from pallas.console.cli.bot_process import bot_lifecycle_available
from pallas.console.webui.community_plugin_deps import install_missing_dependencies
from pallas.core.foundation.paths import PROJECT_ROOT
from pallas.core.shared.utils.git_mirror import (
    BUILTIN_MIRRORS,
    canonical_github_https_url,
    iter_mirrors_for_failover,
    mirror_by_id,
    rewrite_github_url,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    ProgressReporter = Callable[[int, str], None]

COMMUNITY_PLUGINS_DIR = "local/plugins"
INSTALL_TIMEOUT_S = 300.0
UNINSTALL_TIMEOUT_S = 60.0
PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
ALLOWED_GIT_HOSTS = ("github.com", "gitlab.com", "gitee.com", "codeberg.org")
# 子目录插件包布局的安装元数据（放仓库壳外，避免被 git clean 误删）
_INSTALL_META_DIR = ".pallas-install"
_NON_PLUGIN_SUBDIRS = frozenset({"tests", "test"})


def _report(on_progress: ProgressReporter | None, percent: int, message: str) -> None:
    if on_progress is not None:
        on_progress(percent, message)


class CommunityPluginInstallError(Exception):
    def __init__(self, detail: str, *, status_code: int = 400) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


def community_plugins_root() -> Path:
    return PROJECT_ROOT / COMMUNITY_PLUGINS_DIR


def validate_plugin_id(plugin_id: str) -> str:
    pid = (plugin_id or "").strip()
    if not pid or not PLUGIN_ID_RE.fullmatch(pid):
        raise CommunityPluginInstallError("插件 ID 须为小写字母开头，仅含字母数字下划线")
    return pid


def validate_git_repository(url: str) -> str:
    repo = (url or "").strip()
    if not repo:
        raise CommunityPluginInstallError("缺少 git 仓库地址")
    lower = repo.lower()
    if lower.startswith("git@"):
        host_part = repo.split(":", 1)[0]
        host = host_part.split("@", 1)[-1].lower()
    elif lower.startswith(("https://", "http://")):
        host = repo.split("//", 1)[1].split("/", 1)[0].lower()
    else:
        raise CommunityPluginInstallError("仅支持 https:// 或 git@ 形式的 git 仓库")
    if not any(host == h or host.endswith(f".{h}") for h in ALLOWED_GIT_HOSTS):
        raise CommunityPluginInstallError(f"不支持的 git 主机：{host}")
    if ".." in repo or "\0" in repo:
        raise CommunityPluginInstallError("非法仓库地址")
    return repo


def webui_community_install_enabled() -> bool:
    return shutil.which("git") is not None


def extra_plugin_dirs_ready() -> bool:
    from pallas.core.foundation.config.repo_settings import resolve_extra_plugin_dirs

    want = COMMUNITY_PLUGINS_DIR.replace("\\", "/").rstrip("/")
    for d in resolve_extra_plugin_dirs():
        norm = d.strip().replace("\\", "/").rstrip("/")
        if norm == want:
            return True
    return False


def tail_output(text: str, *, limit: int = 2000) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[-limit:]


async def run_git_command(timeout_s: float, *args: str, cwd: str | None = None) -> tuple[int, str, str]:
    if shutil.which("git") is None:
        raise CommunityPluginInstallError(
            "未找到 git 命令，请在本体环境安装 git 或手工 clone 到 local/plugins/",
            status_code=503,
        )
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd or str(PROJECT_ROOT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:  # noqa: UP041
        proc.kill()
        await proc.wait()
        raise CommunityPluginInstallError("git 命令超时", status_code=504) from None
    out = out_b.decode(errors="replace").strip() if out_b else ""
    err = err_b.decode(errors="replace").strip() if err_b else ""
    return int(proc.returncode or 0), out, err


def plugin_install_path(plugin_id: str) -> Path:
    return community_plugins_root() / validate_plugin_id(plugin_id)


def local_plugin_installed(plugin_id: str) -> bool:
    path = plugin_install_path(plugin_id)
    return path.is_dir() and (path / "__init__.py").is_file()


def _install_meta_path(plugin_id: str) -> Path:
    return community_plugins_root() / _INSTALL_META_DIR / f"{validate_plugin_id(plugin_id)}.json"


def _read_install_meta(plugin_id: str) -> dict[str, str] | None:
    try:
        data = json.loads(_install_meta_path(plugin_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_install_meta(plugin_id: str, meta: dict[str, str]) -> None:
    path = _install_meta_path(plugin_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _clear_install_meta(plugin_id: str) -> None:
    try:
        _install_meta_path(plugin_id).unlink()
    except OSError:
        pass


def _find_subdir_plugin_package(dest: Path) -> Path | None:
    """仓库根目录无 __init__.py 时，定位子目录插件包（pyproject 声明优先）。"""
    from pallas.core.platform.bot_runtime.pyproject_plugins import parse_nonebot_plugin_config

    modules, _dirs = parse_nonebot_plugin_config(dest / "pyproject.toml")
    for mod in modules:
        top = mod.split(".", 1)[0]
        candidate = dest / top
        if candidate.is_dir() and (candidate / "__init__.py").is_file():
            return candidate
    candidates = [
        entry
        for entry in dest.iterdir()
        if entry.is_dir() and entry.name not in _NON_PLUGIN_SUBDIRS and (entry / "__init__.py").is_file()
    ]
    return candidates[0] if len(candidates) == 1 else None


def _promote_subdir_plugin(dest: Path, subdir: Path) -> None:
    """把子目录插件包内容提升到仓库根目录，使 local/plugins/<id>/__init__.py 直接存在。"""
    for item in sorted(subdir.iterdir(), key=lambda p: p.name):
        target = dest / item.name
        if target.exists():
            raise CommunityPluginInstallError(
                f"插件包子目录 {subdir.name} 与仓库根目录存在同名文件 {item.name}，无法自动适配",
                status_code=502,
            )
        try:
            shutil.move(str(item), str(target))
        except OSError as e:
            raise CommunityPluginInstallError(
                f"插件包子目录 {subdir.name} 提升失败：{e}",
                status_code=502,
            ) from e
    shutil.rmtree(subdir)


async def install_community_plugin(
    plugin_id: str,
    *,
    repository_url: str,
    ref: str = "main",
    on_progress: ProgressReporter | None = None,
) -> dict[str, str | bool]:
    pid = validate_plugin_id(plugin_id)
    repo = validate_git_repository(repository_url)
    branch = (ref or "main").strip() or "main"
    dest = plugin_install_path(pid)
    _report(on_progress, 5, "准备安装…")
    if dest.exists():
        raise CommunityPluginInstallError(
            f"local/plugins/{pid} 已存在，请先卸载或手工更新",
            status_code=409,
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info(
        "Community plugin [{}] is being installed from repository [{}] at ref [{}]",
        pid,
        repo,
        branch,
    )
    last_detail = ""
    clone_ok = False
    out = ""
    _report(on_progress, 15, "git clone…")
    for mirror in iter_mirrors_for_failover("community"):
        clone_url = rewrite_github_url(repo, mirror)
        code, out, err = await run_git_command(
            INSTALL_TIMEOUT_S,
            "clone",
            "--depth",
            "1",
            "--branch",
            branch,
            clone_url,
            str(dest),
        )
        if code == 0:
            clone_ok = True
            break
        last_detail = err or out or "(无输出)"
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
    if not clone_ok:
        raise CommunityPluginInstallError(
            f"git clone 失败：{tail_output(last_detail)}",
            status_code=502,
        )
    _report(on_progress, 80, "校验插件包…")
    if not (dest / "__init__.py").is_file():
        subdir = _find_subdir_plugin_package(dest)
        if subdir is None:
            shutil.rmtree(dest, ignore_errors=True)
            raise CommunityPluginInstallError(
                "clone 完成但目录缺少 __init__.py，不是有效 NoneBot 插件包",
                status_code=502,
            )
        try:
            _promote_subdir_plugin(dest, subdir)
        except CommunityPluginInstallError:
            shutil.rmtree(dest, ignore_errors=True)
            raise
        _write_install_meta(pid, {"layout": "subdir", "subdir": subdir.name, "plugin_id": pid})
    _report(on_progress, 85, "安装依赖…")
    installed_deps, still_missing, deps_error = await install_missing_dependencies(dest, on_progress=on_progress)
    if still_missing:
        shutil.rmtree(dest, ignore_errors=True)
        raise CommunityPluginInstallError(
            f"依赖安装失败：{deps_error}。请手动执行：uv pip install {' '.join(still_missing)}",
            status_code=502,
        )
    _report(on_progress, 92, "依赖安装完成")
    dirs_ready = extra_plugin_dirs_ready()
    msg = f"已安装到 local/plugins/{pid}/。"
    if not dirs_ready:
        msg += ' 请在 config/pallas.toml 的 [bootstrap].extra_plugin_dirs 加入 "local/plugins"。'
    _report(on_progress, 95, "安装完成")
    return {
        "plugin_id": pid,
        "local_path": f"{COMMUNITY_PLUGINS_DIR}/{pid}/",
        "installed": True,
        "needs_restart": True,
        "extra_plugin_dirs_ready": dirs_ready,
        "restart_available": bot_lifecycle_available(),
        "deps_installed": installed_deps,
        "deps_missing": still_missing,
        "message": msg,
        "stdout_tail": tail_output(out),
    }


async def update_community_plugin(
    plugin_id: str,
    *,
    ref: str = "main",
    on_progress: ProgressReporter | None = None,
) -> dict[str, str | bool]:
    pid = validate_plugin_id(plugin_id)
    branch = (ref or "main").strip() or "main"
    dest = plugin_install_path(pid)
    _report(on_progress, 5, "准备更新…")
    if not local_plugin_installed(pid):
        raise CommunityPluginInstallError(f"local/plugins/{pid} 未安装，无法更新")
    logger.info("Community plugin [{}] is being updated to ref [{}]", pid, branch)
    code, remote_url, err = await run_git_command(
        INSTALL_TIMEOUT_S,
        "remote",
        "get-url",
        "origin",
        cwd=str(dest),
    )
    if code != 0 or not remote_url:
        raise CommunityPluginInstallError(
            f"无法读取 git origin：{tail_output(err or '无 remote')}",
            status_code=502,
        )
    canonical = canonical_github_https_url(remote_url)
    # origin 可能是镜像 URL（WebUI 镜像切换改写），git insteadOf 无法把它还原；
    # 统一 canonical 化后逐镜像生成显式 fetch URL，保证 failover 对任意形态 origin 都生效。
    if canonical is None:
        base_mirror = mirror_by_id("github") or BUILTIN_MIRRORS[0]
        mirrors = [base_mirror]
    else:
        mirrors = list(iter_mirrors_for_failover("community"))
    last_detail = ""
    update_ok = False
    out = ""
    for mirror in mirrors:
        fetch_url = rewrite_github_url(canonical or remote_url, mirror)
        _report(on_progress, 25, "git fetch…")
        code, out, err = await run_git_command(
            INSTALL_TIMEOUT_S,
            "fetch",
            fetch_url,
            branch,
            cwd=str(dest),
        )
        if code != 0:
            last_detail = err or out or "(无输出)"
            continue
        _report(on_progress, 55, "同步到最新提交…")
        code, out, err = await run_git_command(
            INSTALL_TIMEOUT_S,
            "reset",
            "--hard",
            "FETCH_HEAD",
            cwd=str(dest),
        )
        if code != 0:
            last_detail = err or out or "(无输出)"
            continue
        update_ok = True
        break
    if not update_ok:
        raise CommunityPluginInstallError(
            f"git fetch 失败：{tail_output(last_detail)}",
            status_code=502,
        )
    _report(on_progress, 85, "校验插件包…")
    meta = _read_install_meta(pid)
    if meta and meta.get("layout") == "subdir":
        subdir_name = str(meta.get("subdir") or "")
        if subdir_name:
            code, _out, _err = await run_git_command(
                INSTALL_TIMEOUT_S,
                "clean",
                "-fdx",
                cwd=str(dest),
            )
            if code == 0:
                subdir = dest / subdir_name
                if subdir.is_dir() and (subdir / "__init__.py").is_file():
                    _promote_subdir_plugin(dest, subdir)
    if not (dest / "__init__.py").is_file():
        raise CommunityPluginInstallError(
            "更新后目录缺少 __init__.py，不是有效 NoneBot 插件包",
            status_code=502,
        )
    _report(on_progress, 90, "安装依赖…")
    installed_deps, still_missing, deps_error = await install_missing_dependencies(dest, on_progress=on_progress)
    if still_missing:
        raise CommunityPluginInstallError(
            f"依赖安装失败：{deps_error}。请手动执行：uv pip install {' '.join(still_missing)}",
            status_code=502,
        )
    _report(on_progress, 94, "依赖安装完成")
    dirs_ready = extra_plugin_dirs_ready()
    msg = f"已更新 local/plugins/{pid}/。"
    if not dirs_ready:
        msg += ' 请在 config/pallas.toml 的 [bootstrap].extra_plugin_dirs 加入 "local/plugins"。'
    _report(on_progress, 95, "更新完成")
    return {
        "plugin_id": pid,
        "local_path": f"{COMMUNITY_PLUGINS_DIR}/{pid}/",
        "installed": True,
        "needs_restart": True,
        "extra_plugin_dirs_ready": dirs_ready,
        "restart_available": bot_lifecycle_available(),
        "deps_installed": installed_deps,
        "deps_missing": still_missing,
        "message": msg,
        "stdout_tail": tail_output(out),
    }


async def uninstall_community_plugin(
    plugin_id: str,
    *,
    on_progress: ProgressReporter | None = None,
) -> dict[str, str | bool]:
    pid = validate_plugin_id(plugin_id)
    dest = plugin_install_path(pid)
    _report(on_progress, 5, "准备删除…")
    if not dest.is_dir():
        _report(on_progress, 100, "无需删除")
        return {
            "plugin_id": pid,
            "installed": False,
            "needs_restart": True,
            "already_removed": True,
            "message": f"local/plugins/{pid} 不存在，无需卸载。",
        }
    logger.info("Community plugin [{}] is being uninstalled", pid)
    _report(on_progress, 40, f"删除 local/plugins/{pid}/…")
    try:
        shutil.rmtree(dest)
    except OSError as e:
        raise CommunityPluginInstallError(f"删除目录失败：{e}", status_code=502) from e
    _clear_install_meta(pid)
    _report(on_progress, 95, "删除完成")
    return {
        "plugin_id": pid,
        "installed": False,
        "needs_restart": True,
        "already_removed": False,
        "message": f"已删除 local/plugins/{pid}/，请重启 Bot 后生效。",
    }
