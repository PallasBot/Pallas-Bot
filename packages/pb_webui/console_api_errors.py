"""控制台 API 统一错误 JSON（OPT-WEB-013）：保留 FastAPI detail，附加 ok/error。"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def register_console_api_exception_handlers(app: FastAPI, *, api_prefix: str) -> None:
    prefix = (api_prefix or "/pallas/api").rstrip("/")

    def under_console(path: str) -> bool:
        return path == prefix or path.startswith(prefix + "/")

    @app.exception_handler(HTTPException)
    async def console_http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        path = request.url.path
        if not under_console(path):
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        detail = exc.detail
        error = detail if isinstance(detail, str) else str(detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"ok": False, "error": error, "detail": detail},
        )

    @app.exception_handler(RequestValidationError)
    async def console_validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        path = request.url.path
        errors: Any = exc.errors()
        if not under_console(path):
            return JSONResponse(status_code=422, content={"detail": errors})
        return JSONResponse(
            status_code=422,
            content={"ok": False, "error": "validation_error", "detail": errors},
        )
