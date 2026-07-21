#!/usr/bin/env python3
"""将主仓 docs/ 同步到 Pallas-Bot-Docs 的 VitePress src/。

插件页约定：
- 主仓权威正文：`docs/plugins/<name>/README.md`（相对链接，便于 GitHub 浏览）
- 文档站呈现：`src/plugins/<name>.md`（由本脚本变换链接后写出）
- 勿在 Docs 仓长期手改扁平插件页后再拷回主仓；改插件说明请改 README 再 sync
- `docs/plugins/*.md` 扁平副本仅保留归档 stub（ollama / pallas_* 等），正式插件勿双份维护
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs"

# docs/ 相对路径 -> VitePress src/ 相对路径
# 权威入口：maintainer/ + developer/；guide / plugins / common / develop 兼容页
FILE_MAP: dict[str, str] = {
    # --- Maintainer（运维权威）---
    "maintainer/quickstart.md": "maintainer/quickstart.md",
    "maintainer/install/bot.md": "maintainer/install/bot.md",
    "maintainer/install/webui.md": "maintainer/install/webui.md",
    "maintainer/install/protocol.md": "maintainer/install/protocol.md",
    "maintainer/install/official-extensions.md": "maintainer/install/official-extensions.md",
    "maintainer/install/ai-runtime.md": "maintainer/install/ai-runtime.md",
    "maintainer/install/ga-install-checklist.md": "maintainer/install/ga-install-checklist.md",
    "maintainer/deploy/single-process.md": "maintainer/deploy/single-process.md",
    "maintainer/deploy/docker.md": "maintainer/deploy/docker.md",
    "maintainer/deploy/sharded.md": "maintainer/deploy/sharded.md",
    "maintainer/deploy/upgrade.md": "maintainer/deploy/upgrade.md",
    "maintainer/operate/webui.md": "maintainer/operate/webui.md",
    "maintainer/operate/llm-and-ai.md": "maintainer/operate/llm-and-ai.md",
    "maintainer/operate/command-permissions.md": "maintainer/operate/command-permissions.md",
    "maintainer/operate/plugin-governance.md": "maintainer/operate/plugin-governance.md",
    "maintainer/operate/troubleshooting.md": "maintainer/operate/troubleshooting.md",
    "maintainer/operate/hot-reload-pre-reload-checklist.md": (
        "maintainer/operate/hot-reload-pre-reload-checklist.md"
    ),
    "maintainer/reference/config.md": "maintainer/reference/config.md",
    "maintainer/reference/cli.md": "maintainer/reference/cli.md",
    "maintainer/reference/api.md": "maintainer/reference/api.md",
    "maintainer/reference/glossary.md": "maintainer/reference/glossary.md",
    # --- Developer（开发权威）---
    "developer/index.md": "developer/index.md",
    "developer/author/index.md": "developer/author/index.md",
    "developer/architecture/overview.md": "developer/architecture/overview.md",
    "developer/architecture/core-vs-extensions.md": "developer/architecture/core-vs-extensions.md",
    "developer/architecture/config-storage.md": "developer/architecture/config-storage.md",
    "developer/architecture/plugin-governance.md": "developer/architecture/plugin-governance.md",
    "developer/architecture/shard-runtime.md": "developer/architecture/shard-runtime.md",
    "developer/plugin-development/getting-started.md": (
        "developer/plugin-development/getting-started.md"
    ),
    "developer/plugin-development/first-plugin.md": (
        "developer/plugin-development/first-plugin.md"
    ),
    "developer/plugin-development/golden-plugin.md": (
        "developer/plugin-development/golden-plugin.md"
    ),
    "developer/plugin-development/metadata.md": "developer/plugin-development/metadata.md",
    "developer/plugin-development/config-and-webui.md": (
        "developer/plugin-development/config-and-webui.md"
    ),
    "developer/plugin-development/dynamic-config-panel.md": (
        "developer/plugin-development/dynamic-config-panel.md"
    ),
    "developer/plugin-development/reload-and-activation.md": (
        "developer/plugin-development/reload-and-activation.md"
    ),
    "developer/plugin-development/knowledge-sources.md": (
        "developer/plugin-development/knowledge-sources.md"
    ),
    "developer/plugin-development/pallas-api-cookbook.md": (
        "developer/plugin-development/pallas-api-cookbook.md"
    ),
    "developer/plugin-development/testing.md": "developer/plugin-development/testing.md",
    "developer/plugin-development/publishing.md": "developer/plugin-development/publishing.md",
    "developer/reference/repo-layout.md": "developer/reference/repo-layout.md",
    "developer/reference/platform-api.md": "developer/reference/platform-api.md",
    "developer/reference/internal-api.md": "developer/reference/internal-api.md",
    "developer/reference/console-api-response.md": "developer/reference/console-api-response.md",
    # --- 兼容：根部署页 / FAQ ---
    "Deployment.md": "deploy/deployment.md",
    "DockerDeployment.md": "deploy/docker.md",
    "Config.md": "deploy/config.md",
    "FAQ.md": "deploy/faq.md",
    "Migration-v3.md": "about/migration.md",
    # --- common / develop 兼容 ---
    "common/community_stats.md": "common/community_stats.md",
    "common/corpus/README.md": "common/corpus.md",
    "common/cmd_perm/README.md": "common/cmd_perm.md",
    "common/command_limits/README.md": "common/command_limits.md",
    "common/webui/README.md": "common/webui.md",
    "common/webui/api/README.md": "common/webui/api/index.md",
    "common/webui/api/01-auth-health.md": "common/webui/api/01-auth-health.md",
    "common/webui/api/02-plugins.md": "common/webui/api/02-plugins.md",
    "common/webui/api/03-common-config.md": "common/webui/api/03-common-config.md",
    "common/webui/api/04-stats-dashboard.md": "common/webui/api/04-stats-dashboard.md",
    "common/webui/api/05-social.md": "common/webui/api/05-social.md",
    "common/webui/api/06-database.md": "common/webui/api/06-database.md",
    "common/webui/api/07-instances-configs.md": "common/webui/api/07-instances-configs.md",
    "common/webui/api/08-update-ai.md": "common/webui/api/08-update-ai.md",
    "common/message_scrub/README.md": "common/message_scrub.md",
    "plugins/README.md": "plugins/index.md",
    "develop/README.md": "develop/index.md",
    # 现行正文在 developer/；develop/ 仅 stub，由 Docs 仓维护
    "developer/environment.md": "developer/environment.md",
    "developer/workflow.md": "developer/workflow.md",
    "developer/webui.md": "developer/webui.md",
    "developer/extension-pypi-publish.md": "developer/extension-pypi-publish.md",
    "develop/environment.md": "develop/environment.md",
    "develop/workflow.md": "develop/workflow.md",
    "develop/webui.md": "develop/webui.md",
    "develop/knowledge-sources.md": "develop/knowledge-sources.md",
    # --- Guide 上手 ---
    "guide/quickstart.md": "guide/quickstart.md",
    "guide/install-source.md": "guide/install-source.md",
    "guide/connect-qq.md": "guide/connect-qq.md",
    "guide/install-extensions.md": "guide/install-extensions.md",
    "guide/install-plugins.md": "guide/install-plugins.md",
    "guide/advanced.md": "guide/advanced.md",
    "guide/web-console.md": "guide/web-console.md",
    "guide/ai.md": "guide/ai.md",
    "guide/usage.md": "guide/usage.md",
    "guide/bot-owner.md": "guide/bot-owner.md",
    "guide/config.md": "guide/config.md",
    "guide/concepts.md": "guide/concepts.md",
    "guide/4.0-start.md": "guide/4.0-start.md",
    "guide/4.0-migration.md": "guide/4.0-migration.md",
    "guide/community-plugin-store.md": "guide/community-plugin-store.md",
    "guide/community-plugin-author.md": "guide/community-plugin-author.md",
    "guide/llm-and-repeater.md": "guide/llm-and-repeater.md",
    "guide/llm-migrate-from-ollama.md": "guide/llm-migrate-from-ollama.md",
    "user/README.md": "guide/usage-admin.md",
    "develop/extension-pypi-publish.md": "develop/extension-pypi-publish.md",
}

PLUGIN_NAMES = [
    "blacklist",
    "bot_status",
    "chat",
    "dream",
    "drink",
    "duel",
    "greeting",
    "help",
    "maa",
    "draw",
    "pb_protocol",
    "pb_webui",
    "pb_core",
    "pb_stats",
    "relogin_bot",
    "repeater",
    "request_handler",
    "roulette",
    "sing",
    "who_is_spy",
    "llm_chat",
    "persona",
    "take_name",
]

for name in PLUGIN_NAMES:
    FILE_MAP[f"plugins/{name}/README.md"] = f"plugins/{name}.md"

# 历史站内路径别名（Docs 仓旧链接）
FILE_MAP["plugins/pb_webui/README.md"] = "plugins/pb_webui.md"
FILE_MAP["plugins/pb_protocol/README.md"] = "plugins/pb_protocol.md"

GITHUB_SRC = "https://github.com/PallasBot/Pallas-Bot/tree/main/pallas/"


def transform_for_vitepress(text: str) -> str:
    """相对链接 -> VitePress 站内路径；源码路径 -> GitHub。"""
    # 插件 README 头像：主仓相对路径 -> Docs 公共静态资源（勿用站 logo）
    text = text.replace("../assets/brand-avatar.png", "/assets/brand-avatar.png")
    text = text.replace("./assets/brand-avatar.png", "/assets/brand-avatar.png")
    text = re.sub(r"(?<![./])assets/brand-avatar\.png", "/assets/brand-avatar.png", text)
    text = text.replace("../assets/concepts-topology.png", "/assets/concepts-topology.png")
    text = text.replace("./assets/concepts-topology.png", "/assets/concepts-topology.png")
    text = re.sub(r"(?<![./])assets/concepts-topology\.png", "/assets/concepts-topology.png", text)
    # 技能 / 源码：站内或 GitHub，避免相对路径 404
    text = re.sub(
        r"\]\((?:\.\./)*common/command_limits/README\.md([^)]*)\)",
        r"](/common/command_limits\1)",
        text,
    )
    text = re.sub(
        r"\]\((?:\.\./)*skills/([^)#]+)\)",
        r"](https://github.com/PallasBot/Pallas-Bot/blob/main/docs/skills/\1)",
        text,
    )
    text = re.sub(
        r"\]\((?:\.\./)*packages/([^)#]+)\)",
        r"](https://github.com/PallasBot/Pallas-Bot/tree/main/packages/\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./CHANGELOG\.md([^)]*)\)",
        r"](https://github.com/PallasBot/Pallas-Bot/blob/main/CHANGELOG.md\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./\.\./\.\./(?:src|pallas)/([^)#]+)\)",
        rf"]({GITHUB_SRC}\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./\.\./(?:src|pallas)/([^)#]+)\)",
        rf"]({GITHUB_SRC}\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./(?:src|pallas)/([^)#]+)\)",
        rf"]({GITHUB_SRC}\1)",
        text,
    )
    # 任意深度相对路径 → 站内插件页（含 common/webui/api 的 ../../../plugins/...）
    text = re.sub(
        r"\]\((?:\.\./)+plugins/([a-z0-9_]+)/README\.md([^)]*)\)",
        r"](/plugins/\1\2)",
        text,
    )
    text = re.sub(
        r"\]\(plugins/([a-z0-9_]+)/README\.md([^)]*)\)",
        r"](/plugins/\1\2)",
        text,
    )
    # common/webui 等指向同级 common 文档（须在下方 ../name → plugins 之前）
    text = re.sub(
        r"\]\(\.\./(cmd_perm|command_limits|message_scrub|corpus|webui)/README\.md([^)]*)\)",
        r"](/common/\1\2)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./community_stats\.md([^)]*)\)",
        r"](/common/community_stats\1)",
        text,
    )
    text = re.sub(
        r"\]\((?:\./)?api/README\.md([^)]*)\)",
        r"](/common/webui/api/\1)",
        text,
    )
    # 误写的绝对路径兜底（cmd_perm 在 common，不在 plugins）
    text = re.sub(r"\]\(/plugins/cmd_perm([^)]*)\)", r"](/common/cmd_perm\1)", text)
    # plugins/<name>/README.md 内互链：../peer/README.md（须在 common 同级变换之后）
    text = re.sub(
        r"\]\(\.\./([a-z0-9_]+)/README\.md([^)]*)\)",
        r"](/plugins/\1\2)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./TEMPLATE\.md([^)]*)\)",
        r"](https://github.com/PallasBot/Pallas-Bot/blob/main/docs/plugins/TEMPLATE.md\1)",
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
        r"\]\(architecture/bot_process_sharding\.md([^)]*)\)",
        r"](/maintainer/deploy/sharded\1)",
        text,
    )
    text = re.sub(
        r"\]\(architecture/settings-storage\.md([^)]*)\)",
        r"](/developer/architecture/config-storage\1)",
        text,
    )
    text = re.sub(
        r"\]\(architecture/site-customization-and-updates\.md([^)]*)\)",
        r"](/maintainer/deploy/upgrade\1)",
        text,
    )
    text = re.sub(
        r"\]\(architecture/plugin-convention\.md([^)]*)\)",
        r"](/developer/plugin-development/golden-plugin\1)",
        text,
    )
    text = re.sub(
        r"\]\(architecture/hot-reload-tiers\.md([^)]*)\)",
        r"](/developer/plugin-development/reload-and-activation\1)",
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
        r"\]\((?:\.\./)+DockerDeployment\.md([^)]*)\)",
        r"](/deploy/docker\1)",
        text,
    )
    text = re.sub(
        r"\]\((?:\.\./)+Deployment\.md([^)]*)\)",
        r"](/deploy/deployment\1)",
        text,
    )
    text = re.sub(
        r"\]\((?:\.\./)+FAQ\.md([^)]*)\)",
        r"](/deploy/faq\1)",
        text,
    )
    text = re.sub(
        r"\]\((?:\.\./)+Config\.md([^)]*)\)",
        r"](/deploy/config\1)",
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
        r"\]\(\.\./(?:pallas_protocol|pb_protocol)/README\.md([^)]*)\)",
        r"](/plugins/pb_protocol\1)",
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
        r"\]\(\.\./plugins/README\.md([^)]*)\)",
        r"](/plugins/index\1)",
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
        rf"](https://github.com/PallasBot/Pallas-Bot/tree/main/resource/\1)",
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
    text = re.sub(r"\]\(guide/([a-z0-9.-]+)\.md([^)]*)\)", r"](/guide/\1\2)", text)
    text = re.sub(r"\]\(\.\./guide/([a-z0-9.-]+)\.md([^)]*)\)", r"](/guide/\1\2)", text)
    text = re.sub(r"\]\(\.\./\.\./guide/([a-z0-9.-]+)\.md([^)]*)\)", r"](/guide/\1\2)", text)
    text = re.sub(
        r"\]\(\.\./\.\./scripts/([^)#]+)\)",
        r"](https://github.com/PallasBot/Pallas-Bot/tree/main/scripts/\1)",
        text,
    )
    for guide_page in ("quickstart", "concepts", "install-source"):
        text = re.sub(
            rf"\]\({guide_page}\.md([^)]*)\)",
            rf"](/guide/{guide_page}\1)",
            text,
        )
    text = re.sub(r"\]\(\.\./user/README\.md([^)]*)\)", r"](/guide/usage-admin\1)", text)
    text = re.sub(r"\]\(user/README\.md([^)]*)\)", r"](/guide/usage-admin\1)", text)
    text = re.sub(
        r"\]\(\.\./develop/README\.md([^)]*)\)",
        r"](/develop/index\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./maintainer/deploy/sharded\.md([^)]*)\)",
        r"](/maintainer/deploy/sharded\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./common/community_stats\.md([^)]*)\)",
        r"](/common/community_stats\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./\.\./skills/([^)#]+)\)",
        rf"](https://github.com/PallasBot/Pallas-Bot/blob/main/docs/skills/\1)",
        text,
    )
    text = re.sub(
        r"\]\(\.\./skills/([^)#]+)\)",
        rf"](https://github.com/PallasBot/Pallas-Bot/blob/main/docs/skills/\1)",
        text,
    )
    text = re.sub(r"\]\(4\.0-start\.md([^)]*)\)", r"](/guide/4.0-start\1)", text)
    text = re.sub(r"\]\(\.\./Config\.md([^)]*)\)", r"](/deploy/config\1)", text)
    text = re.sub(r"\]\(\.\./Deployment\.md([^)]*)\)", r"](/deploy/deployment\1)", text)
    text = re.sub(r"\]\(\.\./Migration-v3\.md([^)]*)\)", r"](/about/migration\1)", text)
    text = re.sub(r"\]\(develop/([a-z0-9_/-]+)\.md([^)]*)\)", r"](/develop/\1\2)", text)
    text = re.sub(r"\]\(\.\./develop/([a-z0-9_/-]+)\.md([^)]*)\)", r"](/develop/\1\2)", text)
    # 已带 maintainer/developer 前缀的链接
    text = re.sub(
        r"\]\((?:\.\./)*(maintainer/[a-z0-9_./-]+)\.md([^)]*)\)",
        r"](/\1\2)",
        text,
    )
    text = re.sub(
        r"\]\((?:\.\./)*(developer/[a-z0-9_./-]+)\.md([^)]*)\)",
        r"](/\1\2)",
        text,
    )
    # 去掉站内链接里的 .md 后缀
    text = re.sub(
        r"(\]\(/(?:deploy|plugins|common|about|guide|maintainer|developer|develop)"
        r"/[a-zA-Z0-9_./-]+)\.md\)",
        r"\1)",
        text,
    )
    return text


def rewrite_tree_relative_links(text: str, *, rel_src: str) -> str:
    """把 maintainer/developer 树内相对链接改成 VitePress 绝对路径。"""
    if rel_src.startswith("maintainer/"):
        text = re.sub(
            r"\]\((?:\.\./)?(install|deploy|operate|reference)/([a-z0-9_./-]+)\.md([^)]*)\)",
            r"](/maintainer/\1/\2\3)",
            text,
        )
        text = re.sub(r"\]\((?:\.\./)?quickstart\.md([^)]*)\)", r"](/maintainer/quickstart\1)", text)
    elif rel_src.startswith("developer/"):
        text = re.sub(
            r"\]\((?:\.\./)?(architecture|plugin-development|reference|author)/"
            r"([a-z0-9_./-]+)\.md([^)]*)\)",
            r"](/developer/\1/\2\3)",
            text,
        )
        text = re.sub(r"\]\((?:\.\./)?index\.md([^)]*)\)", r"](/developer/index\1)", text)
    return text


def sync(dest_root: Path) -> int:
    src_root = dest_root / "src"
    count = 0
    avatar_src = DOCS / "plugins" / "assets" / "brand-avatar.png"
    avatar_dst = src_root / "public" / "assets" / "brand-avatar.png"
    if avatar_src.is_file():
        avatar_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(avatar_src, avatar_dst)
        print("sync plugins/assets/brand-avatar.png -> src/public/assets/brand-avatar.png")
    topo_src = DOCS / "assets" / "concepts-topology.png"
    topo_dst = src_root / "public" / "assets" / "concepts-topology.png"
    if topo_src.is_file():
        topo_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(topo_src, topo_dst)
        print("sync assets/concepts-topology.png -> src/public/assets/concepts-topology.png")
    for rel_src, rel_dst in FILE_MAP.items():
        source = DOCS / rel_src
        if not source.is_file():
            print(f"skip missing: {rel_src}")
            continue
        body = source.read_text(encoding="utf-8")
        body = rewrite_tree_relative_links(body, rel_src=rel_src)
        out = src_root / rel_dst
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(transform_for_vitepress(body), encoding="utf-8")
        count += 1
        print(f"sync {rel_src} -> src/{rel_dst}")
    return count


def sync_plugins_only(dest_root: Path) -> int:
    """只同步 plugins/<name>/README.md → src/plugins/<name>.md。"""
    src_root = dest_root / "src"
    count = 0
    for name in PLUGIN_NAMES:
        rel_src = f"plugins/{name}/README.md"
        rel_dst = f"plugins/{name}.md"
        source = DOCS / rel_src
        if not source.is_file():
            print(f"skip missing: {rel_src}")
            continue
        body = source.read_text(encoding="utf-8")
        body = rewrite_tree_relative_links(body, rel_src=rel_src)
        out = src_root / rel_dst
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(transform_for_vitepress(body), encoding="utf-8")
        count += 1
        print(f"sync {rel_src} -> src/{rel_dst}")
    # 插件索引
    index_src = DOCS / "plugins" / "README.md"
    if index_src.is_file():
        body = transform_for_vitepress(index_src.read_text(encoding="utf-8"))
        (src_root / "plugins" / "index.md").write_text(body, encoding="utf-8")
        count += 1
        print("sync plugins/README.md -> src/plugins/index.md")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync docs/ to Pallas-Bot-Docs VitePress src/")
    parser.add_argument(
        "--dest",
        type=Path,
        default=REPO_ROOT.parent / "Pallas-Bot-Docs",
        help="Pallas-Bot-Docs 仓库根目录",
    )
    parser.add_argument(
        "--plugins-only",
        action="store_true",
        help="仅同步 plugins/<name>/README.md 与插件索引",
    )
    args = parser.parse_args()
    if not args.dest.is_dir():
        raise SystemExit(f"dest not found: {args.dest}")
    n = sync_plugins_only(args.dest) if args.plugins_only else sync(args.dest)
    print(f"done: {n} files")


if __name__ == "__main__":
    main()
