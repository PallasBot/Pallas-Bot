from __future__ import annotations

import argparse  # noqa: TC003
import asyncio
import sys

from pallas.console.cli.community_plugin_ops import (
    CommunityPluginInstallError,
    install_community_plugin_with_options,
    uninstall_community_plugin_with_options,
    update_community_plugin_with_options,
)
from pallas.console.cli.community_plugin_target import resolve_community_plugin_target
from pallas.console.webui.community_plugin_install import (
    local_plugin_installed,
    webui_community_install_enabled,
)


def register(parent: argparse._SubParsersAction) -> None:
    community = parent.add_parser("community", help="社区插件 git 安装与管理")
    community_sub = community.add_subparsers(dest="community_command", required=True)

    list_parser = community_sub.add_parser("list", help="列出社区索引与本地安装状态")
    list_parser.set_defaults(handler=run_list)

    install_parser = community_sub.add_parser("install", help="clone 到 local/plugins/<id>")
    install_parser.add_argument("plugin_id", help="插件 ID，如 interact")
    install_parser.add_argument(
        "--repo",
        dest="repository_url",
        default="",
        help="git 仓库 URL；省略时从社区索引解析",
    )
    install_parser.add_argument("--ref", default="main", help="分支或 tag，默认 main")
    install_parser.add_argument("--restart", action="store_true", help="完成后重启 Bot")
    install_parser.set_defaults(handler=run_install)

    update_parser = community_sub.add_parser("update", help="git pull 已安装的社区插件")
    update_parser.add_argument("plugin_id", help="插件 ID")
    update_parser.add_argument("--ref", default="main", help="分支，默认 main")
    update_parser.add_argument("--restart", action="store_true", help="完成后重启 Bot")
    update_parser.set_defaults(handler=run_update)

    uninstall_parser = community_sub.add_parser("uninstall", help="删除 local/plugins/<id>")
    uninstall_parser.add_argument("plugin_id", help="插件 ID")
    uninstall_parser.add_argument("--restart", action="store_true", help="完成后重启 Bot")
    uninstall_parser.set_defaults(handler=run_uninstall)


def run_list(_args: argparse.Namespace) -> int:
    return asyncio.run(run_list_async())


def run_install(args: argparse.Namespace) -> int:
    return asyncio.run(
        run_install_async(
            args.plugin_id,
            repository_url=args.repository_url,
            ref=args.ref,
            restart=bool(args.restart),
        ),
    )


def run_update(args: argparse.Namespace) -> int:
    return asyncio.run(
        run_update_async(
            args.plugin_id,
            ref=args.ref,
            restart=bool(args.restart),
        ),
    )


def run_uninstall(args: argparse.Namespace) -> int:
    return asyncio.run(run_uninstall_async(args.plugin_id, restart=bool(args.restart)))


async def run_list_async() -> int:
    if not webui_community_install_enabled():
        print("未找到 git 命令，无法管理社区插件", file=sys.stderr)
        return 1

    from pallas.console.webui.community_plugin_index import load_community_plugin_index_safe
    from pallas.console.webui.plugin_registry import loaded_extra_plugin_ids

    index = await load_community_plugin_index_safe()
    rows: list[tuple[str, str, str, str]] = []
    for entry in index.get("plugins") or []:
        plugin_id = str(entry.get("plugin_id") or "").strip()
        if not plugin_id:
            continue
        ref = str(entry.get("ref") or "main")
        installed = "yes" if local_plugin_installed(plugin_id) else "no"
        loaded = "yes" if plugin_id in loaded_extra_plugin_ids([plugin_id]) else "no"
        rows.append((plugin_id, ref, installed, loaded))

    if not rows:
        print("(社区索引为空或未加载)")
        return 0

    id_w = max(len(r[0]) for r in rows)
    ref_w = max(len(r[1]) for r in rows)
    print(f"{'plugin_id'.ljust(id_w)}  {'ref'.ljust(ref_w)}  local  loaded")
    for plugin_id, ref, installed, loaded in sorted(rows):
        print(f"{plugin_id.ljust(id_w)}  {ref.ljust(ref_w)}  {installed:>5}  {loaded:>6}")
    return 0


async def run_install_async(
    plugin_id: str,
    *,
    repository_url: str,
    ref: str,
    restart: bool,
) -> int:
    try:
        pid, repo_url, branch = await resolve_community_plugin_target(
            plugin_id,
            repository_url=repository_url,
            ref=ref,
        )
        result = await install_community_plugin_with_options(
            pid,
            repository_url=repo_url,
            ref=branch,
            restart=restart,
        )
    except CommunityPluginInstallError as e:
        print(e.detail, file=sys.stderr)
        return 1
    print(result.get("message") or "安装完成。")
    return 0


async def run_update_async(
    plugin_id: str,
    *,
    ref: str,
    restart: bool,
) -> int:
    from pallas.console.webui.community_plugin_install import validate_plugin_id

    try:
        pid = validate_plugin_id(plugin_id)
        branch = (ref or "main").strip() or "main"
        result = await update_community_plugin_with_options(
            pid,
            ref=branch,
            restart=restart,
        )
    except CommunityPluginInstallError as e:
        print(e.detail, file=sys.stderr)
        return 1
    print(result.get("message") or "更新完成。")
    return 0


async def run_uninstall_async(plugin_id: str, *, restart: bool) -> int:
    try:
        result = await uninstall_community_plugin_with_options(plugin_id, restart=restart)
    except CommunityPluginInstallError as e:
        print(e.detail, file=sys.stderr)
        return 1
    print(result.get("message") or "卸载完成。")
    return 0
