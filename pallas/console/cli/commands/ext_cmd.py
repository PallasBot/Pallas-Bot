from __future__ import annotations

import argparse  # noqa: TC003
import asyncio
import sys

from pallas.console.cli.extension_ops import (
    ExtensionInstallError,
    install_official_extension_with_options,
    uninstall_official_extension_with_options,
    update_official_extension_with_options,
)
from pallas.console.webui.extension_install import pip_package_installed, webui_extension_install_enabled
from pallas.core.platform.bot_runtime.plugin_matrix import (
    EXTRA_PACKAGE_PRIORITY,
    OFFICIAL_EXTENSION_REPOS,
    uv_extra_for_package,
)


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("ext", help="官方插件安装与管理")
    ext_sub = parser.add_subparsers(dest="ext_command", required=True)

    list_parser = ext_sub.add_parser("list", help="列出官方扩展与安装状态")
    list_parser.set_defaults(handler=run_list)

    install_parser = ext_sub.add_parser("install", help="安装官方扩展")
    install_parser.add_argument("package", help="pip 包名，如 pallas-plugin-duel")
    install_parser.add_argument(
        "--upgrade",
        action="store_true",
        help="兼容 pip/uv 用法；安装命令始终升级到可用最新版本",
    )
    install_parser.add_argument("--restart", action="store_true", help="完成后重启 Bot")
    install_parser.set_defaults(handler=run_install)

    uninstall_parser = ext_sub.add_parser("uninstall", help="卸载官方扩展")
    uninstall_parser.add_argument("package", help="pip 包名")
    uninstall_parser.add_argument("--restart", action="store_true", help="完成后重启 Bot")
    uninstall_parser.set_defaults(handler=run_uninstall)


def run_list(_args: argparse.Namespace) -> int:
    if not webui_extension_install_enabled():
        print("当前环境无法通过 uv 管理扩展（缺少 uv 或 pyproject.toml）", file=sys.stderr)
        return 1

    rows: list[tuple[str, str, str, str]] = []
    for package in sorted(OFFICIAL_EXTENSION_REPOS):
        extra = uv_extra_for_package(package)
        priority = EXTRA_PACKAGE_PRIORITY.get(package, "")
        installed = "yes" if pip_package_installed(package) else "no"
        rows.append((package, extra, priority, installed))

    name_w = max(len(r[0]) for r in rows)
    extra_w = max(len(r[1]) for r in rows)
    print(f"{'package'.ljust(name_w)}  {'uv_extra'.ljust(extra_w)}  pri  installed")
    for package, extra, priority, installed in rows:
        print(f"{package.ljust(name_w)}  {extra.ljust(extra_w)}  {priority:>3}  {installed}")
    return 0


def run_install(args: argparse.Namespace) -> int:
    return asyncio.run(
        run_install_async(
            args.package,
            restart=bool(args.restart),
            upgrade=bool(args.upgrade),
        )
    )


def run_uninstall(args: argparse.Namespace) -> int:
    return asyncio.run(run_uninstall_async(args.package, restart=bool(args.restart)))


async def run_install_async(package: str, *, restart: bool, upgrade: bool = False) -> int:
    try:
        operation = update_official_extension_with_options if upgrade else install_official_extension_with_options
        result = await operation(package, restart=restart)
    except ExtensionInstallError as e:
        print(e.detail, file=sys.stderr)
        return 1
    print(result.get("message") or "安装完成。")
    return 0


async def run_uninstall_async(package: str, *, restart: bool) -> int:
    try:
        result = await uninstall_official_extension_with_options(package, restart=restart)
    except ExtensionInstallError as e:
        print(e.detail, file=sys.stderr)
        return 1
    print(result.get("message") or "卸载完成。")
    return 0
