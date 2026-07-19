#!/usr/bin/env python3
"""一次性迁移：pallas 包布局 + packages 插件 + import 重写。"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PRODUCT_FEATURES = (
    "arknights_kb",
    "ban_gate",
    "community_stats",
    "control_plane",
    "corpus",
    "llm",
    "message_scrub",
    "persona",
    "service_gateways",
)

CORE_FEATURE_MAP = {
    "cmd_perm": "perm",
    "command_limits": "limits",
    "plugin_storage": "storage",
    "plugin_sdk": "commands",
    "plugin_capabilities": "plugin_capabilities",
    "plugin_reload": "plugin_reload",
    "plugin_coord": "plugin_coord",
}

IMPORT_REPLACEMENTS: list[tuple[str, str]] = [
    ("from packages.", "from packages."),
    ("import packages.", "import packages."),
    ('"packages.', '"packages.'),
    ("'packages.", "'packages."),
    ("from pallas.core.foundation.", "from pallas.core.foundation."),
    ("from pallas.core.platform.", "from pallas.core.platform."),
    ("from pallas.core.shared.", "from pallas.core.shared."),
    ("from pallas.core.domain.", "from pallas.core.domain."),
    ("from pallas.console.", "from pallas.console."),
    ("from pallas.product.corpus", "from pallas.product.corpus"),
    ("from pallas.product.persona", "from pallas.product.persona"),
    ("from pallas.product.llm", "from pallas.product.llm"),
    ("from pallas.product.community_stats", "from pallas.product.community_stats"),
    ("from pallas.product.control_plane", "from pallas.product.control_plane"),
    ("from pallas.product.service_gateways", "from pallas.product.service_gateways"),
    ("from pallas.product.ban_gate", "from pallas.product.ban_gate"),
    ("from pallas.product.message_scrub", "from pallas.product.message_scrub"),
    ("from pallas.product.arknights_kb", "from pallas.product.arknights_kb"),
    ("from pallas.core.perm", "from pallas.core.perm"),
    ("from pallas.core.limits", "from pallas.core.limits"),
    ("from pallas.core.storage", "from pallas.core.storage"),
    ("from pallas.core.commands", "from pallas.core.commands"),
    ("from pallas.core.plugin_capabilities", "from pallas.core.plugin_capabilities"),
    ("from pallas.core.plugin_reload", "from pallas.core.plugin_reload"),
    ("from pallas.core.shared.dream_ban_ack_state", "from pallas.core.shared.dream_ban_ack_state"),
    ("from pallas.core.plugin_coord", "from pallas.core.plugin_coord"),
    ("from pallas.product.", "from pallas.product."),
    ("import pallas.core.foundation.", "import pallas.core.foundation."),
    ("import pallas.core.platform.", "import pallas.core.platform."),
    ("import pallas.core.shared.", "import pallas.core.shared."),
    ("import pallas.core.domain.", "import pallas.core.domain."),
    ("import pallas.console.", "import pallas.console."),
    ("import pallas.product.", "import pallas.product."),
]

TEXT_SUFFIXES = {".py", ".md", ".toml", ".yaml", ".yml", ".sh"}


def move_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.move(str(src), str(dst))


def relocate_directories() -> None:
    plugins_src = ROOT / "pallas" / "plugins"
    packages_dst = ROOT / "packages"
    if plugins_src.is_dir():
        if packages_dst.exists():
            shutil.rmtree(packages_dst)
        shutil.move(str(plugins_src), str(packages_dst))
    elif not packages_dst.is_dir():
        raise RuntimeError("packages/ 不存在且 pallas/plugins 已移除，无法继续")
    (packages_dst / "__init__.py").touch(exist_ok=True)

    features_root = ROOT / "pallas" / "features"
    if not features_root.is_dir():
        return

    product_root = ROOT / "pallas" / "product"
    product_root.mkdir(parents=True, exist_ok=True)
    (product_root / "__init__.py").touch(exist_ok=True)

    for name in PRODUCT_FEATURES:
        move_tree(features_root / name, product_root / name)

    for src_name, dst_name in CORE_FEATURE_MAP.items():
        move_tree(features_root / src_name, ROOT / "pallas" / "core" / dst_name)

    loose = features_root / "dream_ban_ack_state.py"
    if loose.is_file():
        shutil.move(str(loose), str(ROOT / "pallas" / "core" / "shared" / "dream_ban_ack_state.py"))

    if features_root.is_dir():
        shutil.rmtree(features_root, ignore_errors=True)


def rewrite_file(path: Path) -> bool:
    if path.suffix not in TEXT_SUFFIXES:
        return False
    if "egg-info" in path.parts or ".venv" in path.parts or ".git" in path.parts:
        return False
    text = path.read_text(encoding="utf-8")
    original = text
    for old, new in IMPORT_REPLACEMENTS:
        text = text.replace(old, new)
    text = text.replace('names.append(f"packages.', 'names.append(f"packages.')
    text = text.replace('"packages.', '"packages.')
    text = text.replace('plugin_dirs = ["packages"]', 'plugin_dirs = ["packages"]')
    text = text.replace('"packages"', '"packages"')
    text = text.replace("'packages'", "'packages'")
    text = text.replace("packages/", "packages/")
    if text == original:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def rewrite_tree(base: Path) -> int:
    count = 0
    if not base.exists():
        return count
    for path in base.rglob("*"):
        if path.is_file() and rewrite_file(path):
            count += 1
    return count


def create_api_facade() -> None:
    api_root = ROOT / "pallas" / "api"
    api_root.mkdir(parents=True, exist_ok=True)
    (api_root / "__init__.py").write_text(
        '"""插件作者稳定入口；详见 docs/developer/architecture/pallas-package-layout.md。"""\n',
        encoding="utf-8",
    )

    facades: dict[str, str] = {
        "commands": "from pallas.core.commands import *  # noqa: F403\n",
        "config": (
            "from pallas.console.webui.plugin_config import install_hot_reload_config\n\n"
            "__all__ = [\"install_hot_reload_config\"]\n"
        ),
        "storage": "from pallas.core.storage import *  # noqa: F403\n",
        "perm": "from pallas.core.perm import *  # noqa: F403\n",
        "limits": (
            "from pallas.core.commands.declare import command_limit_list, command_limit_row\n"
            "from pallas.core.limits import *  # noqa: F403\n"
        ),
        "metadata": (
            "from pallas.core.perm.metadata_defaults import (\n"
            "    PLUGIN_EXTRA_VERSION,\n"
            "    PLUGIN_HOMEPAGE,\n"
            "    PLUGIN_MENU_TEMPLATE,\n"
            ")\n"
            "from pallas.core.perm.metadata_text import (\n"
            "    SCENE_AUTO,\n"
            "    SCENE_BOTH,\n"
            "    SCENE_GROUP,\n"
            "    SCENE_PRIVATE,\n"
            "    join_usage,\n"
            "    usage_line,\n"
            ")\n"
        ),
        "paths": (
            "from pallas.core.foundation.paths import plugin_data_dir, resource_dir\n\n"
            "__all__ = [\"plugin_data_dir\", \"resource_dir\"]\n"
        ),
    }
    for name, body in facades.items():
        sub = api_root / name
        sub.mkdir(exist_ok=True)
        init = sub / "__init__.py"
        if not init.exists():
            init.write_text(body, encoding="utf-8")


def create_runtime_boot() -> None:
    runtime_dir = ROOT / "pallas" / "core" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    boot_path = runtime_dir / "boot.py"
    if boot_path.exists():
        return
    boot_path.write_text(
        '''"""Bot 启动链：供 bot.py / bot_hub.py / bot_worker.py 调用。"""

from __future__ import annotations

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as ONEBOT_V11Adapter
from nonebot.log import logger

from pallas.console.web import install_nonebot_log_sink
from pallas.core.foundation.config.dotenv import apply_repo_settings_to_environ
from pallas.core.foundation.db import init_db
from pallas.core.foundation.logging import apply_stdlib_logging_channel_prefix, resolve_repo_log_level
from pallas.core.foundation.paths import plugin_data_dir
from pallas.core.platform.bot_runtime import load_plugins_for_role
from pallas.core.shared.adapters import register_onebot_v11_custom_events
from pallas.core.shared.utils.voice_downloader import ensure_voices
from pallas.product.ban_gate import start_ban_gate_snapshot, stop_ban_gate_snapshot
from pallas.product.llm.startup_probe import install_llm_startup_probe
from pallas.product.message_scrub import start_message_scrub_if_enabled


def apply_repo_settings() -> None:
    apply_repo_settings_to_environ()


def boot() -> nonebot.Driver:
    apply_stdlib_logging_channel_prefix()
    file_log_level = resolve_repo_log_level()
    nonebot.init()
    bot_log_dir = plugin_data_dir("bot", create=True)
    logger.add(
        bot_log_dir / "nonebot_{time:YYYY-MM-DD_HH-mm-ss_SSSSSS}.log",
        level=file_log_level,
        rotation="50 MB",
        retention="14 days",
        encoding="utf-8",
        enqueue=True,
    )
    logger.info("bot file log dir: {} level={}", bot_log_dir, file_log_level)
    start_message_scrub_if_enabled()
    install_llm_startup_probe()
    install_nonebot_log_sink()
    driver = nonebot.get_driver()
    driver.register_adapter(ONEBOT_V11Adapter)
    register_onebot_v11_custom_events()

    @driver.on_startup
    async def startup() -> None:
        await init_db()
        await start_ban_gate_snapshot()
        await ensure_voices()

    @driver.on_shutdown
    async def shutdown() -> None:
        await stop_ban_gate_snapshot()

    load_plugins_for_role()
    return driver
''',
        encoding="utf-8",
    )
    init_path = runtime_dir / "__init__.py"
    if not init_path.exists():
        init_path.write_text(
            "from .boot import apply_repo_settings, boot\n\n__all__ = [\"apply_repo_settings\", \"boot\"]\n",
            encoding="utf-8",
        )


def rewrite_internal_cross_imports() -> None:
    """features 迁址后，pallas 树内旧 pallas.features 引用。"""
    extra: list[tuple[str, str]] = [
        ("from pallas.product.corpus", "from pallas.product.corpus"),
        ("from pallas.product.persona", "from pallas.product.persona"),
        ("from pallas.product.llm", "from pallas.product.llm"),
        ("from pallas.product.community_stats", "from pallas.product.community_stats"),
        ("from pallas.product.control_plane", "from pallas.product.control_plane"),
        ("from pallas.product.service_gateways", "from pallas.product.service_gateways"),
        ("from pallas.product.ban_gate", "from pallas.product.ban_gate"),
        ("from pallas.product.message_scrub", "from pallas.product.message_scrub"),
        ("from pallas.product.arknights_kb", "from pallas.product.arknights_kb"),
        ("from pallas.core.perm", "from pallas.core.perm"),
        ("from pallas.core.limits", "from pallas.core.limits"),
        ("from pallas.core.storage", "from pallas.core.storage"),
        ("from pallas.core.commands", "from pallas.core.commands"),
        ("from pallas.core.plugin_capabilities", "from pallas.core.plugin_capabilities"),
        ("from pallas.core.plugin_reload", "from pallas.core.plugin_reload"),
        ("from pallas.core.shared.dream_ban_ack_state", "from pallas.core.shared.dream_ban_ack_state"),
        ("from pallas.core.plugin_coord", "from pallas.core.plugin_coord"),
        ("from pallas.product.", "from pallas.product."),
        ("packages/", "packages/"),
        ("f\"packages.", "f\"packages."),
        ("f'packages.", "f'packages."),
    ]
    global IMPORT_REPLACEMENTS
    IMPORT_REPLACEMENTS = extra + IMPORT_REPLACEMENTS


def main() -> None:
    rewrite_internal_cross_imports()
    relocate_directories()
    create_api_facade()
    create_runtime_boot()
    changed = 0
    for rel in ("pallas", "packages", "tests", "tools", "scripts", "."):
        base = ROOT if rel == "." else ROOT / rel
        if rel == ".":
            for name in ("bot.py", "bot_hub.py", "bot_worker.py", "pyproject.toml"):
                p = ROOT / name
                if p.is_file() and rewrite_file(p):
                    changed += 1
            continue
        changed += rewrite_tree(base)
    print(f"rewrote {changed} files")


if __name__ == "__main__":
    main()
