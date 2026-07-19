"""WebUI 官方扩展安装与卸载。"""

from __future__ import annotations

import asyncio
import os
import shutil

from nonebot import logger

from pallas.core.foundation.paths import PROJECT_ROOT
from pallas.core.platform.bot_runtime.plugin_matrix import (
    EXTRA_PACKAGE_MODULES,
    OFFICIAL_EXTENSION_REPOS,
    pip_module_installed,
)

INSTALL_TIMEOUT_S = 600.0
UNINSTALL_TIMEOUT_S = 120.0


class ExtensionInstallError(Exception):
    def __init__(self, detail: str, *, status_code: int = 400) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


def official_extension_packages() -> frozenset[str]:
    return frozenset(OFFICIAL_EXTENSION_REPOS.keys())


def pip_package_installed(package: str) -> bool:
    for mod in EXTRA_PACKAGE_MODULES.get((package or "").strip(), ()):
        if pip_module_installed(mod):
            return True
    return False


def webui_extension_install_enabled() -> bool:
    return (PROJECT_ROOT / "pyproject.toml").is_file() and shutil.which("uv") is not None


def resolve_official_extension_package(package: str) -> str:
    name = (package or "").strip()
    if not name:
        raise ExtensionInstallError("缺少 package")
    if name not in official_extension_packages():
        raise ExtensionInstallError(f"非官方扩展包：{name}")
    return name


async def run_uv_command(timeout_s: float, *args: str) -> tuple[int, str, str]:
    if shutil.which("uv") is None:
        raise ExtensionInstallError(
            "未找到 uv 命令。请在部署环境安装 uv，或在本体目录手动执行安装命令。",
            status_code=503,
        )
    if not (PROJECT_ROOT / "pyproject.toml").is_file():
        raise ExtensionInstallError(
            "当前运行目录无 pyproject.toml（例如仅含镜像内文件）。请使用 docker 构建参数安装扩展，"
            "或将插件放入 local/plugins/。",
            status_code=400,
        )
    env = {**os.environ}
    proc = await asyncio.create_subprocess_exec(
        "uv",
        *args,
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:  # noqa: UP041
        proc.kill()
        await proc.wait()
        raise ExtensionInstallError("uv 命令超时，请检查网络后在命令行重试", status_code=504) from None
    out = out_b.decode(errors="replace").strip() if out_b else ""
    err = err_b.decode(errors="replace").strip() if err_b else ""
    return int(proc.returncode or 0), out, err


def tail_output(text: str, *, limit: int = 2000) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[-limit:]


async def install_official_extension(package: str) -> dict[str, str | bool]:
    pkg = resolve_official_extension_package(package)
    if pip_package_installed(pkg):
        return {
            "package": pkg,
            "pip_installed": True,
            "needs_restart": True,
            "already_installed": True,
            "message": "扩展包已在当前环境中。",
        }
    logger.info("Pallas-Bot 控制台: 安装官方扩展 package={}", pkg)
    code, out, err = await run_uv_command(
        INSTALL_TIMEOUT_S,
        "pip",
        "install",
        "--upgrade",
        pkg,
    )
    if code != 0:
        detail = err or out or "(无输出)"
        raise ExtensionInstallError(f"uv pip install 失败：{tail_output(detail)}", status_code=502)
    if not pip_package_installed(pkg):
        raise ExtensionInstallError(
            "uv pip install 已完成但未检测到扩展模块，请查看日志或手动执行安装命令。",
            status_code=502,
        )
    return {
        "package": pkg,
        "pip_installed": True,
        "needs_restart": True,
        "already_installed": False,
        "message": "安装完成。",
        "stdout_tail": tail_output(out),
    }


async def update_official_extension(package: str) -> dict[str, str | bool]:
    pkg = resolve_official_extension_package(package)
    if not pip_package_installed(pkg):
        raise ExtensionInstallError("扩展未安装，请先安装后再更新")
    logger.info("Pallas-Bot 控制台: 更新官方扩展 package={}", pkg)
    code, out, err = await run_uv_command(
        INSTALL_TIMEOUT_S,
        "pip",
        "install",
        "--upgrade",
        pkg,
    )
    if code != 0:
        detail = err or out or "(无输出)"
        raise ExtensionInstallError(f"uv pip install 失败：{tail_output(detail)}", status_code=502)
    if not pip_package_installed(pkg):
        raise ExtensionInstallError(
            "uv pip install 已完成但未检测到扩展模块，请查看日志或手动执行安装命令。",
            status_code=502,
        )
    return {
        "package": pkg,
        "pip_installed": True,
        "needs_restart": True,
        "message": "更新完成。",
        "stdout_tail": tail_output(out),
    }


async def uninstall_official_extension(package: str) -> dict[str, str | bool]:
    pkg = resolve_official_extension_package(package)
    if not pip_package_installed(pkg):
        return {
            "package": pkg,
            "pip_installed": False,
            "needs_restart": True,
            "already_removed": True,
            "message": "扩展包未通过 pip 安装，无需卸载。",
        }
    logger.info("Pallas-Bot 控制台: 卸载官方扩展 package={}", pkg)
    code, out, err = await run_uv_command(
        UNINSTALL_TIMEOUT_S,
        "pip",
        "uninstall",
        pkg,
    )
    if code != 0:
        detail = err or out or "(无输出)"
        raise ExtensionInstallError(f"uv pip uninstall 失败：{tail_output(detail)}", status_code=502)
    return {
        "package": pkg,
        "pip_installed": False,
        "needs_restart": True,
        "already_removed": False,
        "message": "已卸载 pip 包。",
        "stdout_tail": tail_output(out),
    }
