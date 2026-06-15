"""分片 hub/worker 落盘日志：统一 loguru 格式、轮转、会话标记与 ERROR jsonl。"""

from __future__ import annotations

import os
import pathlib
from datetime import datetime
from typing import Any

from src.platform.shard import context as shard_ctx
from src.platform.shard.logs.errors import append_shard_log_error_from_sink, log_stem_for_shard
from src.platform.shard.logs.session import maybe_rotate_logs_for_new_session
from src.platform.shard.logs.view import shard_logs_dir
from src.platform.shard.registry.config import get_shard_registry_settings

_SHARD_LOG_FORMAT = "{time:MM-DD HH:mm:ss} | {level:<8} | {name}:{line} - {message}"
_FILE_ROTATION = "30 MB"
_FILE_RETENTION = 14
_INSTALLED = False


def shard_log_file_path(*, role: str, shard_id: int) -> str:
    logs_dir = shard_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)
    stem = log_stem_for_shard(role=role, shard_id=shard_id)
    return str(logs_dir / f"{stem}.log")


def install_shard_process_logging() -> str | None:
    """为当前分片进程挂载落盘 loguru sink；返回日志文件路径。"""
    global _INSTALLED
    if _INSTALLED or not shard_ctx.sharding_active():
        return None
    s = get_shard_registry_settings()
    role = s.role
    if role not in ("hub", "worker"):
        return None

    from nonebot.log import logger

    from src.foundation.logging import resolve_repo_log_level

    path = shard_log_file_path(role=role, shard_id=s.shard_id)
    stem = log_stem_for_shard(role=role, shard_id=s.shard_id)
    maybe_rotate_logs_for_new_session(stem=stem, main_log_path=pathlib.Path(path))

    logger.add(
        path,
        level=resolve_repo_log_level(),
        format=_SHARD_LOG_FORMAT,
        rotation=_FILE_ROTATION,
        retention=_FILE_RETENTION,
        encoding="utf-8",
        enqueue=True,
    )

    if role in ("hub", "worker"):
        from src.console.web import set_log_error_capture

        def capture(text: str, record: Any) -> None:
            append_shard_log_error_from_sink(text, record, stem=stem)

        set_log_error_capture(capture)

    _write_session_banner(path, role=role, shard_id=s.shard_id, stem=stem)
    _INSTALLED = True
    return path


def _write_session_banner(path: str, *, role: str, shard_id: int, stem: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pid = os.getpid()
    port = os.environ.get("PORT", "?")
    banner = (
        f"{ts} | INFO     | shard_session:0 - "
        f"=== {stem} START pid={pid} role={role} shard_id={shard_id} port={port} ===\n"
    )
    try:
        with pathlib.Path(path).open("a", encoding="utf-8") as fh:
            fh.write(banner)
    except OSError:
        pass

    try:
        from nonebot.log import logger

        logger.info(
            "shard_session: role={} shard_id={} pid={} log_file={}",
            role,
            shard_id,
            pid,
            path,
        )
    except Exception:
        pass
