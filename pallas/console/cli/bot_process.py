"""包装 run_unified_bot / run_sharded_bot 启停脚本。"""

from __future__ import annotations

import subprocess  # noqa: TC003
import sys
from collections.abc import Sequence  # noqa: TC003
from pathlib import Path  # noqa: TC003

from pallas.console.cli.runtime_mode import resolve_bot_mode
from pallas.core.foundation.paths import PROJECT_ROOT

UNIFIED_SCRIPT = PROJECT_ROOT / "scripts" / "run_unified_bot.sh"
SHARD_SCRIPT = PROJECT_ROOT / "scripts" / "run_sharded_bot.sh"
PALLAS_SCRIPT = PROJECT_ROOT / "scripts" / "pallas"


def script_for_mode(mode: str) -> Path:
    return SHARD_SCRIPT if mode == "shard" else UNIFIED_SCRIPT


def bot_lifecycle_available() -> bool:
    return UNIFIED_SCRIPT.is_file() and SHARD_SCRIPT.is_file()


def run_bot_lifecycle(
    action: str,
    *,
    mode: str = "auto",
    extra_args: Sequence[str] | None = None,
) -> int:
    resolved = resolve_bot_mode(mode)
    script = script_for_mode(resolved)
    if not script.is_file():
        print(f"缺少脚本 {script}", file=sys.stderr)
        return 1
    cmd = ["/bin/bash", str(script), action, *(extra_args or ())]
    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=False)  # noqa: S603
    return int(proc.returncode or 0)


def schedule_bot_restart(
    *,
    mode: str = "auto",
    workers_only: bool = False,
    delay_s: float = 2.0,
) -> bool:
    if not PALLAS_SCRIPT.is_file():
        return False
    try:
        from packages.pb_webui.api import invalidate_health_snapshot
        from packages.pb_webui.restart_state import mark_restart_requested

        mark_restart_requested(workers_only=workers_only)
        invalidate_health_snapshot()
    except Exception:
        pass
    resolved = resolve_bot_mode(mode)
    cmd = f"sleep {delay_s} && exec {PALLAS_SCRIPT} restart --mode {resolved}"
    if workers_only and resolved == "shard":
        cmd += " --workers-only"
    try:
        subprocess.Popen(  # noqa: S603
            ["/bin/bash", "-c", cmd],
            cwd=str(PROJECT_ROOT),
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return True
