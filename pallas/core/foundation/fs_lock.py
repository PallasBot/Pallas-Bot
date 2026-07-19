"""跨进程文件锁与原子写，供分片多 worker 共用落盘。"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@contextmanager
def interprocess_file_lock(lock_path: Path) -> Iterator[None]:
    """fcntl 排他锁；锁文件与数据文件旁路共存。"""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    try:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """唯一 tmp + replace，避免分片下共用固定 .tmp 竞态。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        tmp.replace(path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
