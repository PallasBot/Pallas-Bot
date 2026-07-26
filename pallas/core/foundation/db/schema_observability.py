"""启动期 schema 补全步骤的可观测计数。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nonebot import logger

if TYPE_CHECKING:
    from collections.abc import Callable

_ok: int = 0
_failed: int = 0
_last_error: str = ""
_steps: list[dict[str, Any]] = []


def reset_schema_observability_for_tests() -> None:
    global _ok, _failed, _last_error, _steps
    _ok = 0
    _failed = 0
    _last_error = ""
    _steps = []


def schema_observability_snapshot() -> dict[str, Any]:
    return {
        "ok": _ok,
        "failed": _failed,
        "last_error": _last_error,
        "steps": list(_steps),
    }


def run_schema_ensure_step(name: str, fn: Callable[[Any], None], connection: Any) -> None:
    """执行同步 ensure 步骤并记账；失败记数后重新抛出。"""
    global _ok, _failed, _last_error, _steps
    try:
        fn(connection)
    except Exception as e:  # noqa: BLE001
        _failed += 1
        _last_error = f"{name}: {e}"
        _steps.append({"name": name, "ok": False, "error": str(e)})
        logger.warning("schema ensure failed: {} ({})", name, e)
        raise
    _ok += 1
    _steps.append({"name": name, "ok": True, "error": ""})
