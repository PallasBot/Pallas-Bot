"""插件 pyproject 依赖解析与缺失比对（core 层纯函数）。"""

from __future__ import annotations

import importlib.metadata
import tomllib
from pathlib import Path  # noqa: TC003

from nonebot import logger


def parse_plugin_dependencies(dest: Path) -> list[str]:
    """解析插件 pyproject.toml 的 [project].dependencies。无 pyproject 或无字段返回空列表。"""
    toml_path = dest / "pyproject.toml"
    if not toml_path.is_file():
        return []
    try:
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    deps = data.get("project", {}).get("dependencies")
    if not isinstance(deps, list):
        return []
    return [str(x).strip() for x in deps if str(x).strip()]


def missing_dependencies(requirements: list[str]) -> list[str]:
    """返回未安装或版本不满足的依赖。非法 requirement 跳过并记 warning。"""
    from packaging.requirements import InvalidRequirement, Requirement

    missing: list[str] = []
    for raw in requirements:
        try:
            req = Requirement(raw)
        except InvalidRequirement:
            logger.warning("插件依赖解析失败，跳过：{}", raw)
            continue
        try:
            installed = importlib.metadata.version(req.name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(raw)
            continue
        if not req.specifier.contains(installed):
            missing.append(raw)
    return missing
