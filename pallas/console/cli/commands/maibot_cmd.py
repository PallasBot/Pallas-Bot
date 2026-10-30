from __future__ import annotations

import argparse  # noqa: TC003
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from pallas.console.cli import maibot_install

if TYPE_CHECKING:
    from collections.abc import Callable


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("maibot", help="安装、查看 MaiBot 托管实例与协议")
    maibot_sub = parser.add_subparsers(dest="maibot_command", required=True)

    install = maibot_sub.add_parser("install", help="安装固定版本 MaiBot 到独立目录与虚拟环境")
    install.add_argument("--dir", dest="directory", type=Path, default=None, help="显式指定新的空安装目录")
    install.set_defaults(handler=run_install)

    status = maibot_sub.add_parser("status", help="只读查看源码、Python、协议与托管状态")
    status.set_defaults(handler=run_status)

    terms = maibot_sub.add_parser("terms", help="显示实例当前 EULA 与隐私条款")
    terms.set_defaults(handler=run_terms)

    accept = maibot_sub.add_parser("accept", help="显式确认当前 EULA 与隐私条款")
    accept.add_argument("--eula", action="store_true", required=True, help="确认当前 EULA 文本")
    accept.add_argument("--privacy", action="store_true", required=True, help="确认当前隐私条款文本")
    accept.set_defaults(handler=run_accept)


def _run(operation: Callable[[], int]) -> int:
    try:
        return int(operation())
    except maibot_install.MaiBotInstallError as exc:
        print(f"MaiBot：{exc}", file=sys.stderr)
    except OSError:
        print("MaiBot 操作失败（文件系统 IO 错误）", file=sys.stderr)
    return 1


def run_install(args: argparse.Namespace) -> int:
    def install() -> int:
        maibot_install.install_maibot(args.directory)
        return 0

    return _run(install)


def run_status(_args: argparse.Namespace) -> int:
    return _run(maibot_install.show_status)


def run_terms(_args: argparse.Namespace) -> int:
    return _run(maibot_install.show_terms)


def run_accept(args: argparse.Namespace) -> int:
    return _run(lambda: maibot_install.accept_terms(eula=bool(args.eula), privacy=bool(args.privacy)))
