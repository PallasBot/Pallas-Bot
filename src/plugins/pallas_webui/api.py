"""Pallas 控制台 JSON API 前缀（如 /pallas/api）；健康检查等轻量路由可在此注册或再拆子路由。"""

from __future__ import annotations

import importlib.metadata
import tomllib
from pathlib import Path
from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from nonebot import __version__ as _nb_ver


def register_api(
    app,
    *,
    api_base: str,
    extra_meta: dict[str, Any] | None = None,
) -> None:
    """api_base 为完整前缀，例如 /pallas/api 。"""
    x = (api_base or "/pallas/api").strip()
    if not x.startswith("/"):
        x = "/" + x
    x = x.rstrip("/")  # /pallas/api

    router = APIRouter(tags=["Pallas 控制台"])

    pallas_ver: str
    try:
        root = Path(__file__).resolve().parents[3]
        pyproject = root / "pyproject.toml"
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        pallas_ver = str(data.get("project", {}).get("version", "")).strip() or "unknown"
    except Exception:
        try:
            pallas_ver = importlib.metadata.version("pallas-bot")
        except importlib.metadata.PackageNotFoundError:
            pallas_ver = "unknown"

    @router.get(f"{x}/health", include_in_schema=True)
    async def _health() -> JSONResponse:  # pragma: no cover - 路由注册
        return JSONResponse(
            {
                "ok": True,
                "nonebot2": str(_nb_ver),
                "pallas_bot": pallas_ver,
                "console": (extra_meta or {}),
            },
            status_code=status.HTTP_200_OK,
        )

    app.include_router(router)
