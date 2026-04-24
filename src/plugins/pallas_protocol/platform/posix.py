from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .base import NapcatPlatform


class PosixNapcatPlatform(NapcatPlatform):
    def creation_flags(self) -> int:
        return 0

    def kill_process_tree(self, pid: int) -> None:
        if pid <= 0:
            return
        try:
            os.kill(pid, 15)
        except OSError:
            pass

    def resolve_default_command(self, default_command: str) -> str:
        return default_command

    def detect_qq_path(self, program_dir: Path | None) -> str | None:
        return None

    def resolve_boot_launch(
        self,
        account: dict[str, Any],
        command: str,
        args: list[str],
        env_map: dict[str, str],
        resolve_qq,
    ) -> tuple[str, list[str], dict[str, str], str | None]:
        return command, args, env_map, None

    def collect_qq_nt_hints(self, account: dict[str, Any]) -> list[str]:
        return [str((Path.home() / ".config" / "QQ").resolve())]
