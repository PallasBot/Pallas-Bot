"""AI 扩展日志文件尾部 SSE（按字节偏移续传）。"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


def _sse_data(payload: dict[str, Any], *, event_id: int | None = None) -> str:
    body = json.dumps(payload, ensure_ascii=False)
    if event_id is None:
        return f"data: {body}\n\n"
    return f"id: {event_id}\ndata: {body}\n\n"


def read_ai_log_chunk(
    path: Path,
    *,
    offset: int,
    initial_tail_bytes: int = 64_000,
) -> tuple[int, list[str]]:
    """从 ``offset`` 读完整行；``offset==0`` 且文件更大时先跳到尾部。

    返回 ``(新 offset, 完整行列表)``。未完成行不推进 offset。
    """
    size = path.stat().st_size
    if size < offset:
        offset = 0
    start = offset
    skipped_partial = False
    if offset == 0 and initial_tail_bytes > 0 and size > initial_tail_bytes:
        start = size - initial_tail_bytes
        skipped_partial = True
    with path.open("rb") as fh:
        fh.seek(start)
        raw = fh.read()
    if skipped_partial and raw:
        nl = raw.find(b"\n")
        if nl < 0:
            return size, []
        raw = raw[nl + 1 :]
        start += nl + 1
    if not raw.endswith(b"\n"):
        last_nl = raw.rfind(b"\n")
        if last_nl < 0:
            return start, []
        raw = raw[: last_nl + 1]
    text = raw.decode("utf-8", errors="ignore")
    lines = text.splitlines()
    new_offset = start + len(raw)
    return new_offset, lines


async def iter_ai_log_file_sse(
    path: Path,
    *,
    kind: str,
    last_event_id: int | None = None,
    poll_interval_sec: float = 0.75,
    initial_tail_bytes: int = 64_000,
    missing_message: str | None = None,
) -> AsyncIterator[str]:
    """跟读本地日志文件；``id`` 为读完该行后的文件字节偏移。

    首包 ``type=ready``；路径不可读时发 ``type=error`` 后结束。
    """
    path_s = str(path)
    if not await asyncio.to_thread(path.exists):
        yield _sse_data(
            {
                "type": "error",
                "kind": kind,
                "path": path_s,
                "error": missing_message or "日志文件不存在",
            },
        )
        return

    resume = max(0, int(last_event_id or 0))

    try:
        offset, seed_lines = await asyncio.to_thread(
            read_ai_log_chunk,
            path,
            offset=resume,
            initial_tail_bytes=initial_tail_bytes,
        )
    except OSError as e:
        yield _sse_data(
            {
                "type": "error",
                "kind": kind,
                "path": path_s,
                "error": str(e),
            },
        )
        return

    yield _sse_data({"type": "ready", "kind": kind, "path": path_s})

    pos = resume if resume > 0 else (offset - sum(len(ln.encode("utf-8")) + 1 for ln in seed_lines))
    if pos < 0:
        pos = 0
    for line in seed_lines:
        pos += len(line.encode("utf-8")) + 1
        yield _sse_data(
            {"type": "line", "kind": kind, "path": path_s, "line": line},
            event_id=pos,
        )
    offset = max(offset, pos)

    while True:
        current = offset

        def _poll(start_at: int = current) -> tuple[int, list[str]]:
            try:
                return read_ai_log_chunk(
                    path,
                    offset=start_at,
                    initial_tail_bytes=0,
                )
            except OSError:
                return start_at, []

        new_offset, lines = await asyncio.to_thread(_poll)
        if not lines:
            yield ": heartbeat\n\n"
            await asyncio.sleep(poll_interval_sec)
            continue
        pos = offset
        for line in lines:
            pos += len(line.encode("utf-8")) + 1
            yield _sse_data(
                {"type": "line", "kind": kind, "path": path_s, "line": line},
                event_id=pos,
            )
        offset = new_offset
        await asyncio.sleep(poll_interval_sec)
