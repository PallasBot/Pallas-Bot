"""社区插件 pyproject 依赖安装（解析/比对复用 core 层纯函数）。"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING

from pallas.console.webui.extension_install import run_uv_command, tail_output
from pallas.core.platform.bot_runtime.plugin_deps import (
    missing_dependencies,
    parse_plugin_dependencies,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    ProgressReporter = Callable[[int, str], None]

INSTALL_TIMEOUT_S = 600.0

__all__ = ["parse_plugin_dependencies", "missing_dependencies", "install_missing_dependencies"]


async def install_missing_dependencies(
    dest: Path,
    *,
    on_progress: ProgressReporter | None = None,
) -> tuple[list[str], list[str], str]:
    """解析并安装缺失依赖。

    返回 (已安装列表, 仍缺失列表, 错误详情)。仍缺失非空时错误详情为失败原因。
    """
    requirements = parse_plugin_dependencies(dest)
    missing = missing_dependencies(requirements)
    if not missing:
        return [], [], ""
    if on_progress is not None:
        on_progress(88, "执行 uv pip install…")
    code, out, err = await run_uv_command(INSTALL_TIMEOUT_S, "pip", "install", *missing)
    if code != 0:
        return [], missing, tail_output(err or out or "(无输出)")
    return missing, [], ""
