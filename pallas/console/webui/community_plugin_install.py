"""社区插件安装到 local/plugins/（git clone）。"""

from __future__ import annotations

import asyncio
import re
import shutil
from typing import TYPE_CHECKING

from nonebot import logger

from pallas.console.cli.bot_process import bot_lifecycle_available
from pallas.core.foundation.paths import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

COMMUNITY_PLUGINS_DIR = "local/plugins"
INSTALL_TIMEOUT_S = 300.0
UNINSTALL_TIMEOUT_S = 60.0
PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
ALLOWED_GIT_HOSTS = ("github.com", "gitlab.com", "gitee.com", "codeberg.org")


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


async def install_community_plugin(
    plugin_id: str,
    *,
    repository_url: str,
    ref: str = "main",
) -> dict[str, str | bool]:
    pid = validate_plugin_id(plugin_id)
    repo = validate_git_repository(repository_url)
    branch = (ref or "main").strip() or "main"
    dest = plugin_install_path(pid)
    if dest.exists():
        raise CommunityPluginInstallError(
            f"local/plugins/{pid} 已存在，请先卸载或手工更新",
            status_code=409,
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info(
        "Pallas-Bot 控制台: 安装社区插件 id={} repo={} ref={}",
        pid,
        repo,
        branch,
    )
    code, out, err = await run_git_command(
        INSTALL_TIMEOUT_S,
        "clone",
        "--depth",
        "1",
        "--branch",
        branch,
        repo,
        str(dest),
    )
    if code != 0:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        detail = err or out or "(无输出)"
        raise CommunityPluginInstallError(f"git clone 失败：{tail_output(detail)}", status_code=502)
    if not (dest / "__init__.py").is_file():
        shutil.rmtree(dest, ignore_errors=True)
        raise CommunityPluginInstallError(
            "clone 完成但目录缺少 __init__.py，不是有效 NoneBot 插件包",
            status_code=502,
        )
    dirs_ready = extra_plugin_dirs_ready()
    msg = f"已安装到 local/plugins/{pid}/。"
    if not dirs_ready:
        msg += ' 请在 config/pallas.toml 的 [bootstrap].extra_plugin_dirs 加入 "local/plugins"。'
    return {
        "plugin_id": pid,
        "local_path": f"{COMMUNITY_PLUGINS_DIR}/{pid}/",
        "installed": True,
        "needs_restart": True,
        "extra_plugin_dirs_ready": dirs_ready,
        "restart_available": bot_lifecycle_available(),
        "message": msg,
        "stdout_tail": tail_output(out),
    }


async def update_community_plugin(
    plugin_id: str,
    *,
    ref: str = "main",
) -> dict[str, str | bool]:
    pid = validate_plugin_id(plugin_id)
    branch = (ref or "main").strip() or "main"
    dest = plugin_install_path(pid)
    if not local_plugin_installed(pid):
        raise CommunityPluginInstallError(f"local/plugins/{pid} 未安装，无法更新")
    logger.info("Pallas-Bot 控制台: 更新社区插件 id={} ref={}", pid, branch)
    code, out, err = await run_git_command(
        INSTALL_TIMEOUT_S,
        "fetch",
        "origin",
        branch,
        cwd=str(dest),
    )
    if code != 0:
        detail = err or out or "(无输出)"
        raise CommunityPluginInstallError(f"git fetch 失败：{tail_output(detail)}", status_code=502)
    code, out, err = await run_git_command(
        INSTALL_TIMEOUT_S,
        "reset",
        "--hard",
        f"origin/{branch}",
        cwd=str(dest),
    )
    if code != 0:
        code, out, err = await run_git_command(
            INSTALL_TIMEOUT_S,
            "pull",
            "--ff-only",
            "origin",
            branch,
            cwd=str(dest),
        )
    if code != 0:
        detail = err or out or "(无输出)"
        raise CommunityPluginInstallError(f"git 更新失败：{tail_output(detail)}", status_code=502)
    if not (dest / "__init__.py").is_file():
        raise CommunityPluginInstallError(
            "更新后目录缺少 __init__.py，不是有效 NoneBot 插件包",
            status_code=502,
        )
    dirs_ready = extra_plugin_dirs_ready()
    msg = f"已更新 local/plugins/{pid}/。"
    if not dirs_ready:
        msg += ' 请在 config/pallas.toml 的 [bootstrap].extra_plugin_dirs 加入 "local/plugins"。'
    return {
        "plugin_id": pid,
        "local_path": f"{COMMUNITY_PLUGINS_DIR}/{pid}/",
        "installed": True,
        "needs_restart": True,
        "extra_plugin_dirs_ready": dirs_ready,
        "restart_available": bot_lifecycle_available(),
        "message": msg,
        "stdout_tail": tail_output(out),
    }


async def uninstall_community_plugin(plugin_id: str) -> dict[str, str | bool]:
    pid = validate_plugin_id(plugin_id)
    dest = plugin_install_path(pid)
    if not dest.is_dir():
        return {
            "plugin_id": pid,
            "installed": False,
            "needs_restart": True,
            "already_removed": True,
            "message": f"local/plugins/{pid} 不存在，无需卸载。",
        }
    logger.info("Pallas-Bot 控制台: 卸载社区插件 id={}", pid)
    try:
        shutil.rmtree(dest)
    except OSError as e:
        raise CommunityPluginInstallError(f"删除目录失败：{e}", status_code=502) from e
    return {
        "plugin_id": pid,
        "installed": False,
        "needs_restart": True,
        "already_removed": False,
        "message": f"已删除 local/plugins/{pid}/，请重启 Bot 后生效。",
    }
