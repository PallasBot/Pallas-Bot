#!/usr/bin/env python3
"""社区插件作者 CLI：校验插件目录、生成索引条目、校验 index.json。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pallas.console.webui.community_plugin_author import (  # noqa: E402
    build_index_entry,
    build_index_entry_from_dir,
    format_index_entry_json,
    suggest_plugin_id_from_repo,
    today_index_updated_at,
    validate_community_plugin_dir,
    validate_community_plugin_dir_profile,
    validate_index_file,
)


def cmd_check(args: argparse.Namespace) -> int:
    plugin_dir = Path(args.path).resolve()
    profile = (args.profile or "").upper()
    errors, warnings, profile_data = validate_community_plugin_dir_profile(plugin_dir, profile=profile)
    if errors:
        print("校验未通过：", file=sys.stderr)
        for item in errors:
            print(f"  ✗ {item}", file=sys.stderr)
    else:
        tag = f"（{profile}）" if profile else ""
        print(f"✓ {plugin_dir} 符合社区插件基本结构{tag}")
        print(
            json.dumps(
                profile_data,
                ensure_ascii=False,
                indent=2,
            ),
        )
    if warnings:
        print("建议：")
        for item in warnings:
            print(f"  · {item}")
    return 1 if errors else 0


def cmd_index_entry(args: argparse.Namespace) -> int:
    plugin_dir = Path(args.path).resolve() if args.path else None
    repository = (args.repository or "").strip()
    if not repository:
        print("请提供 --repository（Git 仓库 HTTPS 地址）", file=sys.stderr)
        return 1
    if plugin_dir and plugin_dir.is_dir():
        errors, warnings = validate_community_plugin_dir(plugin_dir)
        for item in warnings:
            print(f"提示：{item}", file=sys.stderr)
        if errors:
            print("目录校验未通过，仍生成条目草稿：", file=sys.stderr)
            for item in errors:
                print(f"  ✗ {item}", file=sys.stderr)
        entry = build_index_entry_from_dir(
            plugin_dir,
            repository=repository,
            ref=args.ref,
            author=args.author or "",
            tags=[t.strip() for t in (args.tags or "").split(",") if t.strip()],
        )
    else:
        plugin_id = (args.id or suggest_plugin_id_from_repo(repository) or "").strip()
        if not plugin_id:
            print("无法推断插件 ID，请使用 --id", file=sys.stderr)
            return 1
        entry = build_index_entry(
            plugin_id=plugin_id,
            name=args.name or plugin_id,
            description=args.description or "",
            repository=repository,
            ref=args.ref,
            author=args.author or "",
            tags=[t.strip() for t in (args.tags or "").split(",") if t.strip()],
        )
    print(format_index_entry_json(entry).rstrip())
    print(
        "\n将上述对象追加到 community-plugin-index 的 index.json → plugins 数组，并更新 updated_at。",
        file=sys.stderr,
    )
    print(f"建议 updated_at: {today_index_updated_at()}", file=sys.stderr)
    return 0


def cmd_validate_index(args: argparse.Namespace) -> int:
    path = Path(args.path).resolve()
    if not path.is_file():
        print(f"文件不存在：{path}", file=sys.stderr)
        return 1
    try:
        meta, plugins, issues = validate_index_file(path)
    except json.JSONDecodeError as e:
        print(f"JSON 无效：{e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"校验失败：{e}", file=sys.stderr)
        return 1
    print(f"✓ {path.name}：{len(plugins)} 条插件")
    updated = meta.get("updated_at")
    if updated:
        print(f"  updated_at: {updated}")
    if issues:
        print("提示：")
        for item in issues:
            print(f"  · {item}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    check_p = sub.add_parser("check", help="校验插件目录结构与 import 规则")
    check_p.add_argument("path", help="插件目录（含 __init__.py）")
    check_p.add_argument(
        "--profile",
        choices=("L1", "L2"),
        default="L1",
        help="校验等级：L1 仅允许 pallas.api.*（社区插件默认）；L2 预留",
    )
    check_p.set_defaults(func=cmd_check)

    entry_p = sub.add_parser("index-entry", help="生成 index.json 单条插件条目")
    entry_p.add_argument("path", nargs="?", help="插件目录（可选，用于读取 PluginMetadata）")
    entry_p.add_argument("--repository", "-r", required=True, help="Git 仓库 HTTPS 地址")
    entry_p.add_argument("--ref", default="main", help="默认分支或 tag")
    entry_p.add_argument("--id", help="插件 ID（省略时从目录名或仓库名推断）")
    entry_p.add_argument("--name", help="显示名称")
    entry_p.add_argument("--description", "-d", help="简介")
    entry_p.add_argument("--author", help="作者 GitHub 用户名")
    entry_p.add_argument("--tags", help="逗号分隔标签")
    entry_p.set_defaults(func=cmd_index_entry)

    validate_p = sub.add_parser("validate-index", help="校验 index.json 格式")
    validate_p.add_argument(
        "path",
        nargs="?",
        default=str(REPO_ROOT / "config" / "community_plugin_index.json"),
        help="index.json 路径",
    )
    validate_p.set_defaults(func=cmd_validate_index)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
