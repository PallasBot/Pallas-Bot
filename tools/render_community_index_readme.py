#!/usr/bin/env python3
"""从 index.json 生成 community-plugin-index README 用的插件列表 Markdown。

索引仓 CI 使用 ``tools/sync_readme.py`` 写回 README；本脚本供 Pallas-Bot 主仓本地预览 bundled 索引。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = REPO_ROOT / "config" / "community_plugin_index.json"


def render_plugin_table(plugins: list[dict]) -> str:
    if not plugins:
        return "_暂无收录插件。_\n"
    lines = [
        "| 名称 | ID | 作者 | 说明 |",
        "| --- | --- | --- | --- |",
    ]
    for item in plugins:
        name = str(item.get("name") or item.get("id") or "").strip()
        pid = str(item.get("id") or item.get("plugin_id") or "").strip()
        author = str(item.get("author") or "").strip().lstrip("@")
        desc = str(item.get("description") or "").strip().replace("|", "\\|")
        repo = str(item.get("repository") or item.get("repository_url") or "").strip()
        homepage = str(item.get("homepage") or "").strip() or repo.removesuffix(".git")
        name_cell = f"[{name}]({homepage})" if homepage else name
        if author:
            author_cell = f"[@{author}](https://github.com/{author})"
        else:
            author_cell = "—"
        lines.append(f"| {name_cell} | `{pid}` | {author_cell} | {desc} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "index",
        nargs="?",
        default=str(DEFAULT_INDEX),
        help="index.json 路径",
    )
    args = parser.parse_args()
    path = Path(args.index).resolve()
    if not path.is_file():
        print(f"文件不存在：{path}", file=sys.stderr)
        return 1
    raw = json.loads(path.read_text(encoding="utf-8"))
    plugins = raw.get("plugins")
    if not isinstance(plugins, list):
        print("index.json 缺少 plugins 数组", file=sys.stderr)
        return 1
    print(render_plugin_table(plugins), end="")
    print(
        "\n索引仓 README 由 CI 自动同步，见 community-plugin-index/tools/sync_readme.py",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
