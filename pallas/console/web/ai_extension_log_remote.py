"""Bot 通过 AI HTTP API 拉取扩展日志（远端 / 本机文件不可用时的回退）。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable

AI_EXTENSION_REMOTE_LOG_API_PATH = "ops/logs"


class AiExtensionHttpJson(Protocol):
    def __call__(
        self,
        *,
        method: str,
        path: str,
        body: dict[str, Any] | None = ...,
    ) -> Awaitable[dict[str, Any]]: ...


def parse_remote_log_payload(
    payload: dict[str, Any] | None,
    *,
    kind: str,
    fallback_url: str = "",
) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    lines_raw = data.get("lines")
    lines = [str(x) for x in lines_raw] if isinstance(lines_raw, list) else []
    error = data.get("error")
    path = str(data.get("path") or fallback_url)
    return {
        "kind": str(data.get("kind") or kind),
        "path": path,
        "lines": lines,
        "error": str(error) if error else None,
        "source": "remote",
    }


def remote_log_error_from_http_result(result: dict[str, Any], *, kind: str) -> dict[str, Any] | None:
    if result.get("ok"):
        return None
    status = int(result.get("status_code") or 0)
    if status == 401:
        return {
            "kind": kind,
            "path": str(result.get("url") or ""),
            "lines": [],
            "error": "AI 服务鉴权失败：请核对 Bot「AI 服务」Bearer Token 与 AI 侧 PALLAS_AI_API_TOKEN",
            "source": "remote",
        }
    return None


async def fetch_remote_ai_extension_logs(
    cfg: dict[str, Any],
    kind: str,
    n: int,
    *,
    http_json: AiExtensionHttpJson,
) -> dict[str, Any] | None:
    """调用 AI ``GET /api/ops/logs``；鉴权失败返回带 error 的 dict，其它失败返回 None。"""
    limit = max(1, min(int(n), 2000))
    result = await http_json(
        method="GET",
        path=f"{AI_EXTENSION_REMOTE_LOG_API_PATH}?kind={kind}&n={limit}",
    )
    auth_err = remote_log_error_from_http_result(result, kind=kind)
    if auth_err is not None:
        return auth_err
    if not result.get("ok"):
        return None
    data = result.get("data")
    if not isinstance(data, dict):
        return None
    parsed = parse_remote_log_payload(data, kind=kind, fallback_url=str(result.get("url") or ""))
    if parsed["error"] and not parsed["lines"]:
        return None
    return parsed


async def iter_remote_ai_extension_logs_sse(
    cfg: dict[str, Any],
    kind: str,
    *,
    http_json: AiExtensionHttpJson,
    poll_interval_sec: float = 1.0,
    poll_lines: int = 300,
) -> AsyncIterator[str]:
    from pallas.console.web.ai_log_sse import _sse_data

    base_url = str(cfg.get("base_url", "")).rstrip("/")
    seen_count = 0
    yield _sse_data(
        {
            "type": "ready",
            "kind": kind,
            "path": f"{base_url}/api/ops/logs",
            "source": "remote",
        },
    )

    while True:
        payload = await fetch_remote_ai_extension_logs(
            cfg,
            kind,
            poll_lines,
            http_json=http_json,
        )
        if payload is None:
            yield ": heartbeat\n\n"
            await asyncio.sleep(poll_interval_sec)
            continue
        if payload.get("error"):
            yield _sse_data(
                {
                    "type": "error",
                    "kind": kind,
                    "path": str(payload.get("path") or ""),
                    "error": str(payload.get("error")),
                },
            )
            return
        lines = payload.get("lines") or []
        if len(lines) < seen_count:
            seen_count = 0
        if len(lines) > seen_count:
            path = str(payload.get("path") or "")
            for line in lines[seen_count:]:
                yield _sse_data(
                    {
                        "type": "line",
                        "kind": kind,
                        "path": path,
                        "line": line,
                        "source": "remote",
                    },
                )
            seen_count = len(lines)
        else:
            yield ": heartbeat\n\n"
        await asyncio.sleep(poll_interval_sec)
