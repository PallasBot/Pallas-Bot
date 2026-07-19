"""控制台 JSON 信封：{ ok, data, error }。"""

from __future__ import annotations

from typing import Any

from starlette.responses import JSONResponse


def api_ok(data: Any = None, *, status_code: int = 200) -> JSONResponse:
    return JSONResponse({"ok": True, "data": data, "error": None}, status_code=status_code)


def api_err(
    message: str,
    *,
    status_code: int = 400,
    data: Any = None,
) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "data": data, "error": str(message or "").strip() or "error"},
        status_code=status_code,
    )
