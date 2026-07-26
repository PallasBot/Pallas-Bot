"""尝试按已保存配置热切换运行时数据库后端。"""

from __future__ import annotations

import os
from typing import Any

from nonebot import logger

from pallas.core.foundation.db.runtime import get_db_backend, normalize_db_backend_name


async def try_rebind_runtime_backend(target: str | None = None) -> dict[str, Any]:
    """
    dispose 当前连接并按环境变量重新 init。
    成功则进程内后端切换；失败时返回 restart_required，不假装成功。
    """
    from pallas.core.foundation.config.repo_settings import apply_repo_settings_to_environ
    from pallas.core.foundation.db import init_db, reset_mongodb_initialized_flag
    from pallas.core.foundation.db.db_health import probe_runtime_db_health, reset_db_health_for_tests
    from pallas.core.foundation.db.pool_budget import clear_pool_budget_runtime_cache
    from pallas.core.foundation.db.repository_pg import dispose_pg

    apply_repo_settings_to_environ()
    wanted = normalize_db_backend_name(target or os.getenv("DB_BACKEND") or get_db_backend())
    previous = normalize_db_backend_name(get_db_backend())
    try:
        await dispose_pg()
    except Exception as e:  # noqa: BLE001
        logger.warning("dispose_pg during rebind failed: {}", e)

    reset_mongodb_initialized_flag()
    clear_pool_budget_runtime_cache()
    reset_db_health_for_tests()

    os.environ["DB_BACKEND"] = wanted
    try:
        # 刷新 nonebot config 上的 db_backend（若已初始化）
        try:
            import nonebot

            nonebot.get_driver().config.db_backend = wanted
        except Exception:  # noqa: BLE001
            pass
        await init_db(wanted)
        health = await probe_runtime_db_health()
        if health.status == "unhealthy":
            return {
                "ok": False,
                "hot_ready": False,
                "restart_required": True,
                "previous": previous,
                "backend": wanted,
                "message": f"已写入配置，但热切换后健康检查未通过：{health.reason or 'unknown'}；请重启 Bot",
            }
        return {
            "ok": True,
            "hot_ready": True,
            "restart_required": False,
            "previous": previous,
            "backend": wanted,
            "message": "已热切换到新后端",
        }
    except Exception as e:  # noqa: BLE001
        logger.exception("runtime rebind failed")
        return {
            "ok": False,
            "hot_ready": False,
            "restart_required": True,
            "previous": previous,
            "backend": wanted,
            "message": f"热切换失败：{e}；配置已保存，请重启 Bot",
        }
