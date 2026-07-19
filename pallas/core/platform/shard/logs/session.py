"""分片进程启动时会话日志归档：当前 worker-N.log 仅保留本次运行，历史进 logs/archive/。"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path  # noqa: TC003

from pallas.core.platform.shard.logs.errors import errors_jsonl_path
from pallas.core.platform.shard.logs.view import shard_logs_dir
from pallas.core.platform.shard.registry.config import _env_bool, _env_int

_ARCHIVE_DIR_NAME = "archive"
_DEFAULT_ARCHIVE_MAX = 8
_DEFAULT_ROTATE_ON_START = True


def log_rotate_on_start_enabled() -> bool:
    return _env_bool("PALLAS_SHARD_LOG_ROTATE_ON_START", _DEFAULT_ROTATE_ON_START)


def log_archive_max_per_stem() -> int:
    return max(1, _env_int("PALLAS_SHARD_LOG_ARCHIVE_MAX", _DEFAULT_ARCHIVE_MAX))


def shard_log_archive_dir() -> Path:
    root = shard_logs_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = root / _ARCHIVE_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_archive_tag() -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{ts}-p{os.getpid()}"


def rotate_file_to_archive(path: Path, *, archive_basename: str) -> Path | None:
    if not path.is_file():
        return None
    try:
        if path.stat().st_size <= 0:
            path.unlink(missing_ok=True)
            return None
    except OSError:
        return None
    dest = shard_log_archive_dir() / archive_basename
    try:
        if dest.is_file():
            dest.unlink()
        path.rename(dest)
    except OSError:
        return None
    return dest


def prune_stem_archives(*, stem: str, max_files: int | None = None) -> list[str]:
    cap = max_files if max_files is not None else log_archive_max_per_stem()
    archive = shard_log_archive_dir()
    if not archive.is_dir():
        return []
    prefix = f"{stem}-"
    candidates: list[Path] = []
    for path in archive.iterdir():
        if not path.is_file():
            continue
        name = path.name
        if name.startswith((prefix, f"{stem}.")):
            candidates.append(path)
    candidates.sort(key=lambda p: p.stat().st_mtime if p.is_file() else 0, reverse=True)
    removed: list[str] = []
    for path in candidates[cap:]:
        try:
            path.unlink()
            removed.append(path.name)
        except OSError:
            pass
    return removed


def maybe_rotate_logs_for_new_session(*, stem: str, main_log_path: Path) -> list[str]:
    """启动新会话前归档非空主日志与 errors jsonl；返回已归档文件名列表。"""
    if not log_rotate_on_start_enabled():
        return []
    tag = session_archive_tag()
    archived: list[str] = []
    main_dest = rotate_file_to_archive(
        main_log_path,
        archive_basename=f"{stem}-{tag}.log",
    )
    if main_dest is not None:
        archived.append(main_dest.name)
    err_path = errors_jsonl_path(stem)
    err_dest = rotate_file_to_archive(
        err_path,
        archive_basename=f"{stem}-{tag}.jsonl",
    )
    if err_dest is not None:
        archived.append(err_dest.name)
    archived.extend(prune_stem_archives(stem=stem))
    return archived
