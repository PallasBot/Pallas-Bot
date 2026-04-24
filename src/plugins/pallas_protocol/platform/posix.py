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
        def _children_map() -> dict[int, list[int]]:
            out: dict[int, list[int]] = {}
            proc_root = Path("/proc")
            for ent in proc_root.iterdir():
                if not ent.name.isdigit():
                    continue
                try:
                    ppid_raw = (ent / "stat").read_text(encoding="utf-8").split()[3]
                    ppid = int(ppid_raw)
                    cpid = int(ent.name)
                except Exception:
                    continue
                out.setdefault(ppid, []).append(cpid)
            return out

        def _collect_descendants(root: int, cmap: dict[int, list[int]]) -> list[int]:
            stack = [root]
            seen: set[int] = set()
            order: list[int] = []
            while stack:
                cur = stack.pop()
                for child in cmap.get(cur, []):
                    if child in seen:
                        continue
                    seen.add(child)
                    stack.append(child)
                    order.append(child)
            return order

        cmap = _children_map()
        descendants = _collect_descendants(pid, cmap)
        for cpid in reversed(descendants):
            try:
                os.kill(cpid, 15)
            except OSError:
                pass
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
