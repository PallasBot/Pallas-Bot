"""插件版本解析：distribution 优先，本地 pyproject 兜底。"""

from __future__ import annotations

import tomllib
from pathlib import Path  # noqa: TC003

from pallas.console.webui import plugin_catalog as _repo
from pallas.core.platform.bot_runtime.plugin_matrix import extra_package_for_plugin


def installed_distribution_version(
    package: str,
    module_name: str,
    *,
    top_level_distributions: dict[str, list[str]] | None = None,
) -> str | None:
    candidates = [extra_package_for_plugin(package)]
    top_level = (module_name or "").split(".", 1)[0]
    if top_level:
        try:
            distributions = top_level_distributions or _repo.importlib.metadata.packages_distributions()
            candidates.extend(distributions.get(top_level, ()))
        except Exception:  # noqa: BLE001
            pass
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return _repo.importlib.metadata.version(candidate)
        except _repo.importlib.metadata.PackageNotFoundError:
            continue
    return None


def plugin_version(
    package: str,
    source: str,
    *,
    package_root: Path | None = None,
    module_name: str = "",
    top_level_distributions: dict[str, list[str]] | None = None,
) -> str | None:
    if top_level_distributions is None:
        installed = _repo.installed_distribution_version(package, module_name)
    else:
        installed = _repo.installed_distribution_version(
            package,
            module_name,
            top_level_distributions=top_level_distributions,
        )
    if installed:
        return installed
    if source not in ("local", "community") or package_root is None:
        return None
    try:
        with (package_root / "pyproject.toml").open("rb") as f:
            project = tomllib.load(f).get("project")
    except (OSError, tomllib.TOMLDecodeError):
        return None
    version = project.get("version") if isinstance(project, dict) else None
    if version is None:
        return None
    return str(version).strip() or None
