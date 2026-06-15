"""从 pyproject.toml 解析 NoneBot 外部插件。"""

from __future__ import annotations

import tomllib
from pathlib import Path  # noqa: TC003

from src.foundation.paths import PROJECT_ROOT

_DEFAULT_LOCAL_PLUGIN_DIR = "src/plugins"


def parse_nonebot_plugin_config(
    toml_path: Path | None = None,
) -> tuple[list[str], list[str]]:
    """
    解析 [tool.nonebot] 的 plugins / plugin_dirs。

    返回 (module_paths, plugin_dirs)，路径相对仓库根目录。
    """
    path = toml_path or (PROJECT_ROOT / "pyproject.toml")
    if not path.is_file():
        return [], []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return [], []
    nonebot_data = data.get("tool", {}).get("nonebot")
    if not isinstance(nonebot_data, dict):
        return [], []

    raw_plugins = nonebot_data.get("plugins", [])
    module_paths: list[str] = []
    if isinstance(raw_plugins, list):
        module_paths.extend(str(x).strip() for x in raw_plugins if str(x).strip())
    elif isinstance(raw_plugins, dict):
        for key, vals in raw_plugins.items():
            if str(key).strip() == "@local":
                continue
            if not isinstance(vals, list):
                continue
            for item in vals:
                s = str(item).strip()
                if s:
                    module_paths.append(s)

    raw_dirs = nonebot_data.get("plugin_dirs", [])
    plugin_dirs: list[str] = []
    if isinstance(raw_dirs, list):
        for item in raw_dirs:
            s = str(item).strip().replace("\\", "/")
            if s:
                plugin_dirs.append(s)
    return module_paths, plugin_dirs


def extra_plugin_dirs_for_role(
    plugin_dirs: list[str],
    *,
    skip_default_local: bool = True,
) -> list[str]:
    """worker 用：排除已在代码里扫描的 src/plugins。"""
    default = _DEFAULT_LOCAL_PLUGIN_DIR.rstrip("/")
    out: list[str] = []
    for d in plugin_dirs:
        norm = d.strip().replace("\\", "/").rstrip("/")
        if not norm:
            continue
        if skip_default_local and norm in (default, f"./{default}"):
            continue
        out.append(d)
    return out
