"""跨进程文件锁与原子写，供分片多 worker 共用落盘。"""

from __future__ import annotations

import os
import sys
import threading
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


def _acquire_win32_lock(fd: int) -> None:
    import msvcrt

    if os.fstat(fd).st_size < 1:
        os.write(fd, b"\0")
    while True:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            # LK_LOCK 最多重试约 10 次后抛 OSError，循环直到拿到锁
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            return
        except OSError:
            time.sleep(0.05)


def _release_win32_lock(fd: int) -> None:
    import msvcrt

    os.lseek(fd, 0, os.SEEK_SET)
    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


@contextmanager
def interprocess_file_lock(lock_path: Path) -> Iterator[None]:
    """跨进程排他锁；Unix 用 fcntl，Windows 用 msvcrt。"""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    try:
        if sys.platform == "win32":
            _acquire_win32_lock(fd)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            if sys.platform == "win32":
                _release_win32_lock(fd)
            else:
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
