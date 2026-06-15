#!/usr/bin/env python3
"""将主仓 docs/ 同步到 Pallas-Bot-Docs 的 VitePress src/。"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs"

# docs/ 相对路径 -> VitePress src/ 相对路径
FILE_MAP: dict[str, str] = {
    "Deployment.md": "deploy/deployment.md",
    "DockerDeployment.md": "deploy/docker.md",
    "Config.md": "deploy/config.md",
    "FAQ.md": "deploy/faq.md",
    "Migration-v3.md": "about/migration.md",
    "architecture/project-structure.md": "architecture/project-structure.md",
    "architecture/plugin-convention.md": "architecture/plugin-convention.md",
    "architecture/settings-storage.md": "architecture/settings-storage.md",
    "architecture/bot_process_sharding.md": "architecture/bot-process-sharding.md",
    "architecture/site-customization-and-updates.md": "architecture/site-customization-and-updates.md",
    "architecture/control-plane-corpus-federation.md": "architecture/control-plane-corpus-federation.md",
    "architecture/common-layers.md": "architecture/common-layers.md",
    "common/community_stats.md": "common/community_stats.md",
    "common/corpus/README.md": "common/corpus.md",
    "common/cmd_perm/README.md": "common/cmd_perm.md",
    "common/webui/README.md": "common/webui.md",
    "common/message_scrub/README.md": "common/message_scrub.md",
    "plugins/README.md": "plugins/index.md",
    "develop/README.md": "develop/index.md",
    "develop/environment.md": "develop/environment.md",
    "develop/workflow.md": "develop/workflow.md",
    "develop/webui.md": "develop/webui.md",
    "develop/plugin/getting-started.md": "develop/plugin/getting-started.md",
    "develop/plugin/structure.md": "develop/plugin/structure.md",
    "develop/plugin/advanced.md": "develop/plugin/advanced.md",
}

PLUGIN_NAMES = [
    "blacklist",
    "block",
    "bot_status",
    "callback",
    "chat",
    "connectivity",
    "dream",
    "drink",
    "duel",
    "greeting",
    "help",
    "maa",
    "draw",
    "pallas_protocol",
    "pallas_webui",
    "relogin_bot",
    "repeater",
    "request_handler",
    "roulette",
    "sing",
    "who_is_spy",
    "ollama",
]

for name in PLUGIN_NAMES:
    FILE_MAP[f"plugins/{name}/README.md"] = f"plugins/{name}.md"

GITHUB_SRC = "https://github.com/PallasBot/Pallas-Bot/tree/main/src/"


def transform_for_vitepress(text: str) -> str:
    """相对链接 -> VitePress 站内路径；源码路径 -> GitHub。"""
    text = re.sub(
        r"\]\(\.\./\.\./\.\./src/([^)#]+)\)",
        rf"]({GITHUB_SRC}\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./\.\./src/([^)#]+)\)",
        rf"]({GITHUB_SRC}\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./\.\./plugins/([a-z0-9_]+)/README\.md([^)]*)\)",
        r"](/plugins/\1\2)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./plugins/([a-z0-9_]+)/README\.md([^)]*)\)",
        r"](/plugins/\1\2)",
        text,
    )
    text = re.sub(
        r"\]\(plugins/([a-z0-9_]+)/README\.md([^)]*)\)",
        r"](/plugins/\1\2)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./\.\./common/([a-z0-9_]+)/README\.md([^)]*)\)",
        r"](/common/\1\2)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./common/([a-z0-9_]+)/README\.md([^)]*)\)",
        r"](/common/\1\2)",
        text,
    )
    text = re.sub(
        r"\]\(common/([a-z0-9_]+)/README\.md([^)]*)\)",
        r"](/common/\1\2)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./\.\./common/community_stats\.md([^)]*)\)",
        r"](/common/community_stats\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./common/corpus/README\.md([^)]*)\)",
        r"](/common/corpus\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./\.\./common/corpus/README\.md([^)]*)\)",
        r"](/common/corpus\1)",
        text,
    )
    text = re.sub(
        r"\]\(common/corpus/README\.md([^)]*)\)",
        r"](/common/corpus\1)",
        text,
    )
    text = re.sub(
        r"\]\(corpus/README\.md([^)]*)\)",
        r"](/common/corpus\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./architecture/control-plane-corpus-federation\.md([^)]*)\)",
        r"](/architecture/control-plane-corpus-federation\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./\.\./architecture/control-plane-corpus-federation\.md([^)]*)\)",
        r"](/architecture/control-plane-corpus-federation\1)",
        text,
    )
    text = re.sub(
        r"\]\(architecture/control-plane-corpus-federation\.md([^)]*)\)",
        r"](/architecture/control-plane-corpus-federation\1)",
        text,
    )
    text = re.sub(
        r"\]\(architecture/bot_process_sharding\.md([^)]*)\)",
        r"](/architecture/bot-process-sharding\1)",
        text,
    )
    text = re.sub(
        r"\]\(architecture/([a-z0-9_-]+)\.md([^)]*)\)",
        r"](/architecture/\1\2)",
        text,
    )
    text = re.sub(
        r"\]\(\./([a-z0-9_]+)/README\.md([^)]*)\)",
        r"](/plugins/\1\2)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./FAQ\.md([^)]*)\)",
        r"](/deploy/faq\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./DockerDeployment\.md([^)]*)\)",
        r"](/deploy/docker\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./Deployment\.md([^)]*)\)",
        r"](/deploy/deployment\1)",
        text,
    )
    text = re.sub(
        r"\]\(\./TEMPLATE\.md([^)]*)\)",
        r"](https://github.com/PallasBot/Pallas-Bot/blob/main/docs/plugins/TEMPLATE.md\1)",
        text,
    )
    text = re.sub(
        r"\]\(\./VISUAL\.md([^)]*)\)",
        r"](https://github.com/PallasBot/Pallas-Bot/blob/main/docs/plugins/help/VISUAL.md\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./\.\./FAQ\.md([^)]*)\)",
        r"](/deploy/faq\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./pallas_protocol/README\.md([^)]*)\)",
        r"](/plugins/pallas_protocol\1)",
        text,
    )
    text = re.sub(r"\]\(Deployment\.md([^)]*)\)", r"](/deploy/deployment\1)", text)
    text = re.sub(r"\]\(DockerDeployment\.md([^)]*)\)", r"](/deploy/docker\1)", text)
    text = re.sub(r"\]\(Config\.md([^)]*)\)", r"](/deploy/config\1)", text)
    text = re.sub(r"\]\(FAQ\.md([^)]*)\)", r"](/deploy/faq\1)", text)
    text = re.sub(r"\]\(Migration-v3\.md([^)]*)\)", r"](/about/migration\1)", text)
    text = re.sub(
        r"\]\(\.\./README\.md([^)]*)\)",
        r"](https://github.com/PallasBot/Pallas-Bot/blob/main/README.md\1)",
        text,
    )
    text = re.sub(
        r"\]\(plugins/README\.md([^)]*)\)",
        r"](/plugins/index\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./config/([^)#]+)\)",
        rf"](https://github.com/PallasBot/Pallas-Bot/tree/main/config/\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./tools/([^)#]+)\)",
        rf"](https://github.com/PallasBot/Pallas-Bot/tree/main/tools/\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./scripts/([^)#]+)\)",
        rf"](https://github.com/PallasBot/Pallas-Bot/tree/main/scripts/\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./Dockerfile([^)]*)\)",
        r"](https://github.com/PallasBot/Pallas-Bot/blob/main/Dockerfile\1)",
        text,
    )
    text = re.sub(r"\]\(DockerDeployment\.md([^)]*)\)", r"](/deploy/docker\1)", text)
    text = re.sub(r"\]\(FAQ\.md([^)]*)\)", r"](/deploy/faq\1)", text)
    text = re.sub(r"\]\(Migration-v3\.md([^)]*)\)", r"](/about/migration\1)", text)
    text = re.sub(
        r"\]\(\.\./\.\./\.\./resource/([^)#]+)\)",
        rf"]({GITHUB_SRC}../resource/\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./\.\./\.\./tools/([^)#]+)\)",
        rf"](https://github.com/PallasBot/Pallas-Bot/tree/main/tools/\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./\.\./\.\./config/([^)#]+)\)",
        rf"](https://github.com/PallasBot/Pallas-Bot/tree/main/config/\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./\.\./\.\./docker-compose\.yml\)",
        r"](https://github.com/PallasBot/Pallas-Bot/blob/main/docker-compose.yml)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./\.\./\.\./scripts/([^)#]+)\)",
        rf"](https://github.com/PallasBot/Pallas-Bot/tree/main/scripts/\1)",
        text,
    )
# 去掉站内链接里的 .md 后缀
    text = re.sub(
        r"(\](/(?:deploy|plugins|architecture|common|about|guide)/[a-zA-Z0-9_./-]+)\.md)",
        r"\1",
        text,
    )
    return text


def sync(dest_root: Path) -> int:
    src_root = dest_root / "src"
    count = 0
    for rel_src, rel_dst in FILE_MAP.items():
        source = DOCS / rel_src
        if not source.is_file():
            print(f"skip missing: {rel_src}")
            continue
        body = source.read_text(encoding="utf-8")
        out = src_root / rel_dst
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(transform_for_vitepress(body), encoding="utf-8")
        count += 1
        print(f"sync {rel_src} -> src/{rel_dst}")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync docs/ to Pallas-Bot-Docs VitePress src/")
    parser.add_argument(
        "--dest",
        type=Path,
        default=REPO_ROOT.parent / "Pallas-Bot-Docs",
        help="Pallas-Bot-Docs 仓库根目录",
    )
    args = parser.parse_args()
    if not args.dest.is_dir():
        raise SystemExit(f"dest not found: {args.dest}")
    n = sync(args.dest)
    print(f"done: {n} files")


if __name__ == "__main__":
    main()
