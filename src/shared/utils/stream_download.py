"""HTTP 流式下载与进度回调。"""

from __future__ import annotations

from collections.abc import Callable  # noqa: TC003
from pathlib import Path  # noqa: TC003
from typing import Literal, TypedDict

import httpx

DEFAULT_STREAM_DOWNLOAD_CHUNK = 256 * 1024
DEFAULT_PROGRESS_PERCENT_STEP = 10
DEFAULT_PROGRESS_BYTES_STEP = 5 * 1024 * 1024
DEFAULT_STREAM_DOWNLOAD_TIMEOUT = httpx.Timeout(300.0, connect=60.0)


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


class StreamDownloadProgressPercent(TypedDict):
    event: Literal["percent"]
    milestone_percent: int
    received: int
    total: int


class StreamDownloadProgressUnknownStep(TypedDict):
    event: Literal["unknown_step"]
    received: int


class StreamDownloadProgressComplete(TypedDict):
    event: Literal["complete"]
    received: int
    total: int | None


StreamDownloadProgress = (
    StreamDownloadProgressPercent | StreamDownloadProgressUnknownStep | StreamDownloadProgressComplete
)


def format_download_byte_size(num_bytes: int) -> str:
    """人类可读的字节大小。"""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KiB"
    return f"{num_bytes / (1024 * 1024):.1f} MiB"


def sync_stream_download_to_file(
    url: str,
    dest: Path,
    *,
    follow_redirects: bool = True,
    timeout: httpx.Timeout | None = None,
    chunk_size: int = DEFAULT_STREAM_DOWNLOAD_CHUNK,
    headers: dict[str, str] | None = None,
    progress_percent_step: int = DEFAULT_PROGRESS_PERCENT_STEP,
    progress_bytes_step: int = DEFAULT_PROGRESS_BYTES_STEP,
    on_progress: Callable[[StreamDownloadProgress], None] | None = None,
) -> int:
    """同步流式 GET 写入 ``dest``；返回写入字节数。

    - 有 ``Content-Length``：按 ``progress_percent_step`` 汇报百分比里程碑
      。
    - 否则按 ``progress_bytes_step`` 汇报已下载量。
    """
    eff_timeout = timeout or DEFAULT_STREAM_DOWNLOAD_TIMEOUT
    hdrs = dict(headers) if headers else {}

    received = 0
    last_pct_logged = 0
    next_bytes_log = progress_bytes_step
    part = dest.with_name(dest.name + ".download")
    dest.parent.mkdir(parents=True, exist_ok=True)
    _unlink_quiet(part)

    try:
        with httpx.Client(follow_redirects=follow_redirects, timeout=eff_timeout, headers=hdrs) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                raw_len = resp.headers.get("content-length")
                total: int | None = int(raw_len) if raw_len and raw_len.isdigit() else None

                with part.open("wb") as out:
                    for chunk in resp.iter_bytes(chunk_size=chunk_size):
                        if not chunk:
                            continue
                        out.write(chunk)
                        received += len(chunk)
                        if on_progress is None:
                            continue
                        if total and total > 0:
                            pct_now = min(100, int(received * 100 / total))
                            while last_pct_logged + progress_percent_step <= pct_now:
                                last_pct_logged += progress_percent_step
                                if last_pct_logged >= 100:
                                    break
                                on_progress(
                                    {
                                        "event": "percent",
                                        "milestone_percent": last_pct_logged,
                                        "received": received,
                                        "total": total,
                                    },
                                )
                        elif received >= next_bytes_log:
                            on_progress({"event": "unknown_step", "received": received})
                            next_bytes_log = received + progress_bytes_step

        dest.unlink(missing_ok=True)
        part.replace(dest)

        if on_progress is not None:
            on_progress({"event": "complete", "received": received, "total": total})

    except BaseException:
        _unlink_quiet(part)
        raise

    return received
