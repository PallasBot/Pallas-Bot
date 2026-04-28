# ruff: noqa: TC003
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class NapcatPlatform(ABC):
    """与操作系统相关的 NapCat 启动与进程行为（下载逻辑在 ``runtime`` 层）。"""

    @abstractmethod
    def creation_flags(self) -> int:
        """``asyncio.create_subprocess_exec(..., creationflags=...)``。"""

    @abstractmethod
    def kill_process_tree(self, pid: int) -> None:
        """尽力结束以 ``pid`` 为根的进程树。"""

    @abstractmethod
    def resolve_default_command(self, default_command: str) -> str:
        """例如 Windows 上为 ``node`` 解析到绝对路径。"""

    @abstractmethod
    def detect_qq_path(self, program_dir: Path | None) -> str | None:
        """Windows：注册表或便携包；其它平台：无。"""

    @abstractmethod
    def resolve_boot_launch(
        self,
        account: dict[str, Any],
        command: str,
        args: list[str],
        env_map: dict[str, str],
        resolve_qq,
    ) -> tuple[str, list[str], dict[str, str], str | None]:
        """返回 ``(command, args, env, cwd_override)``；无特殊启动链时原样返回。"""

    @abstractmethod
    def collect_qq_nt_hints(self, account: dict[str, Any]) -> list[str]:
        """QQ NT 可能落点（启发式），用于管理页说明。"""

    def should_set_home_to_workdir(self) -> bool:
        """是否在启动时为非 Windows 设置 ``HOME=NAPCAT_WORKDIR``。"""
        return os.name != "nt"
