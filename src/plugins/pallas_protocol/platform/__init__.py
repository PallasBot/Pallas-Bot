"""跨平台适配：下载/解压以外的差异集中在启动与进程控制（POSIX / Windows）。"""

from __future__ import annotations

import os

from .base import NapcatPlatform
from .posix import PosixNapcatPlatform


def get_napcat_platform() -> NapcatPlatform:
    if os.name == "nt":
        from .windows import WindowsNapcatPlatform

        return WindowsNapcatPlatform()
    return PosixNapcatPlatform()


__all__ = ["NapcatPlatform", "PosixNapcatPlatform", "get_napcat_platform"]
