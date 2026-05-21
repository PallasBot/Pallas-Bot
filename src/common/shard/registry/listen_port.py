"""分片 hub/worker 监听端口：在 nonebot.init 后同步到 driver.config。"""

from __future__ import annotations

import os


def apply_listen_port(port: int) -> None:
    """写入 PORT 环境变量，并在 driver 已创建时覆盖 config.port。"""
    os.environ["PORT"] = str(int(port))
    try:
        import nonebot

        driver = nonebot.get_driver()
        if hasattr(driver, "config") and hasattr(driver.config, "port"):
            driver.config.port = int(port)
    except (RuntimeError, ValueError, TypeError):
        pass
