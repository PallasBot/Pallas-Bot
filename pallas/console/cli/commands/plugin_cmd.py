from __future__ import annotations

import argparse  # noqa: TC003
import sys

from pallas.console.cli.commands.community_plugin_cmd import register as register_community_plugin
from pallas.core.plugin_reload.reload_ops import PluginReloadError, execute_plugin_reload


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("plugin", help="插件运维")
    plugin_sub = parser.add_subparsers(dest="plugin_command", required=True)

    reload_parser = plugin_sub.add_parser("reload", help="按 reload_policy 重载插件")
    reload_parser.add_argument("name", help="插件 ID，如 help、pb_webui、draw")
    reload_parser.set_defaults(handler=run_reload)

    register_community_plugin(plugin_sub)


def run_reload(args: argparse.Namespace) -> int:
    try:
        result = execute_plugin_reload(args.name)
    except PluginReloadError as e:
        print(e.detail, file=sys.stderr)
        return 1

    print(result.get("message") or "完成。")
    return 0 if result.get("ok") else 1
