"""htmlrender 渲染后端可用性探测：缺失浏览器时给出启动指引。"""

from __future__ import annotations

import os
from importlib import import_module

from loguru import logger

_RENDER_MODULE = "nonebot_plugin_htmlrender.render"
_CONSTS_MODULE = "nonebot_plugin_htmlrender.consts"


async def probe_htmlrender_backend() -> None:
    """探测默认渲染后端是否可用；不可用时提示缺浏览器与其安装命令。

    渲染后端名取自环境变量 ``RENDER_BACKEND``（框架启动默认注入为
    ``playwright``）。仅做提示不阻塞启动：后端缺失只影响依赖出图的插件
    （如森空岛、未来 help 渲染），不影响 Bot 其余功能。
    """
    try:
        consts_mod = import_module(_CONSTS_MODULE)
        render_mod = import_module(_RENDER_MODULE)
    except Exception:
        return

    backend = (os.environ.get("RENDER_BACKEND") or "").strip().lower()
    if not backend:
        return
    try:
        enum_backend = consts_mod.RenderBackend(backend)
    except ValueError:
        logger.warning("htmlrender 渲染后端 [{}] 未识别，跳过可用性探测", backend)
        return

    try:
        available = render_mod.is_render_backend_available(enum_backend)
    except Exception:
        return
    if available:
        return

    status = render_mod.get_render_backend_status(enum_backend)
    reason = status.reason or "未提供具体原因"
    if enum_backend == consts_mod.RenderBackend.PLAYWRIGHT:
        hint = "请执行 `playwright install chromium` 安装浏览器（国内可用镜像 `PLAYWRIGHT_DOWNLOAD_HOST`）"
    else:
        hint = f"请检查渲染后端 [{enum_backend.value}] 的安装与配置"
    logger.warning(
        "htmlrender 渲染后端 [{}] 当前不可用（{}）。依赖渲染出图的插件（森空岛等）将无法出图。{}",
        backend,
        reason,
        hint,
    )
