from __future__ import annotations

from fastapi import FastAPI  # noqa: TC002
from nonebot import logger

from .http_api import GetTaskResponse, current_maa_http_paths, maa_get_task, maa_report_status

_mounted_paths: frozenset[str] = frozenset()


def unmount_maa_http_routes(app: FastAPI) -> None:
    """移除 worker 侧 MAA 路由。"""
    global _mounted_paths
    if not _mounted_paths:
        return
    app.router.routes = [route for route in app.router.routes if getattr(route, "path", None) not in _mounted_paths]
    _mounted_paths = frozenset()
    logger.info("maa http routes unmounted")


def remount_maa_http_routes(app: FastAPI) -> None:
    """按当前配置挂载 getTask / reportStatus；路径变更时移除旧路由。"""
    global _mounted_paths
    get_path, report_path = current_maa_http_paths()
    new_paths = frozenset({get_path, report_path})
    if new_paths == _mounted_paths:
        return

    if _mounted_paths:
        app.router.routes = [route for route in app.router.routes if getattr(route, "path", None) not in _mounted_paths]

    app.add_api_route(
        get_path,
        maa_get_task,
        methods=["POST"],
        response_model=GetTaskResponse,
        name="maa_get_task",
    )
    app.add_api_route(
        report_path,
        maa_report_status,
        methods=["POST"],
        name="maa_report_status",
    )
    _mounted_paths = new_paths
    logger.info("maa http routes remounted: getTask={} reportStatus={}", get_path, report_path)
