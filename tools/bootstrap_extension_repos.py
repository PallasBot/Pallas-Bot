#!/usr/bin/env python3
"""从本体 src/plugins 生成官方扩展仓（首包实体迁出脚手架）。"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

BOTS_ROOT = Path("/root/Projects/Bots")
MAIN_ROOT = BOTS_ROOT / "Pallas-Bot"
PLUGINS_ROOT = MAIN_ROOT / "src" / "plugins"
LICENSE = MAIN_ROOT / "LICENSE"

REPOS: list[dict[str, object]] = [
    {
        "dir": "Pallas-Plugin-Duel",
        "pip_name": "pallas-plugin-duel",
        "title": "牛牛决斗",
        "description": "Pallas-Bot 官方扩展：泰拉风味多幕决斗（含分片 QTE 与八角笼）。",
        "uv_extra": "plugins-duel",
        "copies": [("duel", "pallas_plugin_duel")],
        "nonebot_plugins": {"pallas-plugin-duel": ["pallas_plugin_duel"]},
        "readme_file": "pallas-plugin-duel.md",
    },
    {
        "dir": "Pallas-Plugin-Maa",
        "pip_name": "pallas-plugin-maa",
        "title": "MAA 远控",
        "description": "Pallas-Bot 官方扩展：QQ 远控 MAA 与分片 hub 入口。",
        "uv_extra": "plugins-maa",
        "copies": [
            ("maa", "pallas_plugin_maa"),
            ("maa_hub", "pallas_plugin_maa_hub"),
        ],
        "nonebot_plugins": {
            "pallas-plugin-maa": ["pallas_plugin_maa"],
            "pallas-plugin-maa-hub": ["pallas_plugin_maa_hub"],
        },
        "readme_file": "pallas-plugin-maa.md",
    },
    {
        "dir": "Pallas-Plugin-Who-Is-Spy",
        "pip_name": "pallas-plugin-who-is-spy",
        "title": "谁是卧底",
        "description": "Pallas-Bot 官方扩展：多牛分片谁是卧底。",
        "uv_extra": "plugins-who-is-spy",
        "copies": [("who_is_spy", "pallas_plugin_who_is_spy")],
        "nonebot_plugins": {"pallas-plugin-who-is-spy": ["pallas_plugin_who_is_spy"]},
        "readme_file": "pallas-plugin-who-is-spy.md",
    },
    {
        "dir": "Pallas-Plugin-Protocol",
        "pip_name": "pallas-plugin-protocol",
        "title": "协议端与重登",
        "description": "Pallas-Bot 官方扩展：NapCat/SnowLuma 协议端管理、牛牛重新上号与分片转发。",
        "uv_extra": "plugins-protocol",
        "copies": [
            ("pallas_protocol", "pallas_plugin_protocol"),
            ("relogin_bot", "pallas_plugin_relogin_bot"),
            ("relogin_forward", "pallas_plugin_relogin_forward"),
        ],
        "copy_overrides": {
            "relogin_bot": {"src.plugins.pallas_protocol": "pallas_plugin_protocol"},
        },
        "nonebot_plugins": {
            "pallas-plugin-protocol": ["pallas_plugin_protocol"],
            "pallas-plugin-relogin-bot": ["pallas_plugin_relogin_bot"],
            "pallas-plugin-relogin-forward": ["pallas_plugin_relogin_forward"],
        },
        "readme_file": "pallas-plugin-protocol.md",
    },
]

GITIGNORE = """.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
dist/
*.egg-info/
.env
data/
"""

AGENTS_TEMPLATE = """# AGENTS.md

## 项目

- **名称**：{pip_name}
- **类型**：Pallas-Bot 4.0 官方扩展（NoneBot 插件包）
- **Python**：3.12+
- **依赖**：`uv` · 运行时依赖 [Pallas-Bot](https://github.com/PallasBot/Pallas-Bot) `>=4.0`

## 本地开发

```bash
uv sync --group dev
uv run ruff check src/
uv run ruff format --check src/
```

与本体联调：在本体仓库执行 `uv pip install -e ../{dir}`，或在扩展仓根目录 `uv.toml` 中配置 `pallas-bot` 的 path 源。

## 约定

- 仅改 `src/`；通过 `pallas-bot` 公开 API（`src.features` / `src.platform`）访问内核，勿反向依赖本体 `src/plugins`。
- 分片协调在插件 `on_startup` 调用 `register_*_coord()`（见本体 `src/features/plugin_coord/`）。
- 提交前 `ruff check` + `ruff format --check` 通过。
"""


def rewrite_imports(text: str, src_plugin: str, pkg_module: str) -> str:
    legacy = f"src.plugins.{src_plugin}"
    out = text.replace(legacy, pkg_module)
    # maa 包内勿误改 maa_hub 前缀（仅 maa 单包迁移时）
    if src_plugin == "maa":
        out = out.replace("pallas_plugin_maa_hub", "src.plugins.maa_hub")
    return out


def copy_plugin_tree(
    src_dir: Path,
    dst_dir: Path,
    src_plugin: str,
    pkg_module: str,
    *,
    import_replacements: dict[str, str] | None = None,
) -> None:
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    for path in src_dir.rglob("*"):
        rel = path.relative_to(src_dir)
        target = dst_dir / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if path.suffix == ".pyc":
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".py":
            content = path.read_text(encoding="utf-8")
            content = rewrite_imports(content, src_plugin, pkg_module)
            for old, new in (import_replacements or {}).items():
                content = content.replace(old, new)
            target.write_text(content, encoding="utf-8")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            shutil.copy2(path, target)
            continue
        target.write_text(text, encoding="utf-8")


def render_pyproject(meta: dict[str, object], package_modules: list[str]) -> str:
    pip_name = str(meta["pip_name"])
    description = str(meta["description"])
    nb_plugins = meta["nonebot_plugins"]
    assert isinstance(nb_plugins, dict)
    nb_lines = "\n".join(f'{k} = {v}' for k, v in nb_plugins.items())
    hatch_packages = ", ".join(f'"{m}"' for m in package_modules)
    return f"""[project]
name = "{pip_name}"
version = "4.0.0"
description = "{description}"
readme = "README.md"
license = {{ file = "LICENSE" }}
requires-python = ">=3.12,<4.0"
dependencies = [
    "nonebot2>=2.4.0",
    "nonebot-adapter-onebot>=2.4.6",
]

[dependency-groups]
dev = [
    "ruff>=0.11.13",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = [{hatch_packages}]

[tool.nonebot]
plugin_dirs = []
builtin_plugins = []

[tool.nonebot.plugins]
"@local" = []
{nb_lines}

[tool.nonebot.adapters]
"@local" = []
nonebot-adapter-onebot = [{{ name = "OneBot V11", module_name = "nonebot.adapters.onebot.v11" }}]
"""


def render_readme(meta: dict[str, object]) -> str:
    readme_file = meta.get("readme_file")
    if isinstance(readme_file, str):
        path = MAIN_ROOT / "templates/pallas-plugin-extension/readmes" / readme_file
        if path.is_file():
            return path.read_text(encoding="utf-8")
    pip_name = str(meta["pip_name"])
    title = str(meta["title"])
    return f"# {pip_name}\n\nPallas-Bot 4.0 官方扩展：**{title}**。\n"


def bootstrap_repo(meta: dict[str, object]) -> Path:
    repo_dir = BOTS_ROOT / str(meta["dir"])
    src_root = repo_dir / "src"
    src_root.mkdir(parents=True, exist_ok=True)

    copies = meta["copies"]
    assert isinstance(copies, list)
    copy_overrides = meta.get("copy_overrides", {})
    assert isinstance(copy_overrides, dict)
    package_modules: list[str] = []
    for item in copies:
        if isinstance(item, tuple) and len(item) == 2:
            src_name, pkg_module = item
        else:
            raise ValueError(f"invalid copies entry: {item!r}")
        assert isinstance(src_name, str) and isinstance(pkg_module, str)
        overrides = copy_overrides.get(src_name, {})
        assert isinstance(overrides, dict)
        copy_plugin_tree(
            PLUGINS_ROOT / src_name,
            src_root / pkg_module,
            src_name,
            pkg_module,
            import_replacements={str(k): str(v) for k, v in overrides.items()},
        )
        package_modules.append(pkg_module)

    (repo_dir / "pyproject.toml").write_text(render_pyproject(meta, package_modules), encoding="utf-8")
    (repo_dir / "README.md").write_text(render_readme(meta), encoding="utf-8")
    (repo_dir / "AGENTS.md").write_text(
        AGENTS_TEMPLATE.format(pip_name=meta["pip_name"], dir=meta["dir"]),
        encoding="utf-8",
    )
    (repo_dir / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    shutil.copy2(LICENSE, repo_dir / "LICENSE")

    if not (repo_dir / ".git").exists():
        subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)

    src_glob = str(src_root)
    subprocess.run(["uv", "run", "ruff", "check", src_glob, "--fix"], cwd=MAIN_ROOT, check=False)
    subprocess.run(["uv", "run", "ruff", "format", src_glob], cwd=MAIN_ROOT, check=False)

    return repo_dir


def main() -> None:
    for meta in REPOS:
        path = bootstrap_repo(meta)
        print(f"ok {path}")


if __name__ == "__main__":
    main()
