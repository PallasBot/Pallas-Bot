"""Bot 侧 AI 扩展日志读取（本机文件优先，HTTP 回退）。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pallas.console.web.ai_extension_log_remote import (
    AiExtensionHttpJson,
    fetch_remote_ai_extension_logs,
)
from pallas.console.web.ai_extension_logs import (
    ai_extension_log_missing_message,
    resolve_log_path_for_kind,
)
from pallas.console.web.ai_log_sse import read_ai_log_chunk


async def read_ai_extension_logs_payload(
    cfg: dict[str, Any],
    kind: str,
    n: int,
    *,
    http_json: AiExtensionHttpJson,
    is_allowed_log_path: Any,
) -> dict[str, Any]:
    limit = max(1, min(int(n), 2000))
    path_s = resolve_log_path_for_kind(cfg, kind)
    if path_s and is_allowed_log_path(path_s):
        p = Path(path_s)
        try:
            exists = await asyncio.to_thread(p.is_file)
        except OSError:
            exists = False
        if exists:
            try:
                _, lines = await asyncio.to_thread(
                    read_ai_log_chunk,
                    p,
                    offset=0,
                    initial_tail_bytes=256_000,
                )
                return {
                    "kind": kind,
                    "path": path_s,
                    "lines": lines[-limit:],
                    "error": None,
                    "source": "local",
                }
            except OSError as e:
                return {
                    "kind": kind,
                    "path": path_s,
                    "lines": [],
                    "error": str(e),
                    "source": "local",
                }

    remote = await fetch_remote_ai_extension_logs(cfg, kind, limit, http_json=http_json)
    if remote is not None:
        return remote

    if path_s and not is_allowed_log_path(path_s):
        return {
            "kind": kind,
            "path": path_s,
            "lines": [],
            "error": "日志路径越界，已拒绝",
            "source": "local",
        }

    return {
        "kind": kind,
        "path": path_s,
        "lines": [],
        "error": ai_extension_log_missing_message(cfg, path_s=path_s, remote_tried=True),
        "source": "none",
    }
