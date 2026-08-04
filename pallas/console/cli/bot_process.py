"""包装 Bot 启停：unified / shard 均走 Python（跨平台）。"""

from __future__ import annotations

import sys
import time
from collections.abc import Sequence  # noqa: TC003
from pathlib import Path  # noqa: TC003

from pallas.console.cli.process_util import spawn_detached
from pallas.console.cli.runtime_mode import resolve_bot_mode
from pallas.console.cli.shard_lifecycle import run_shard_action
from pallas.console.cli.unified_lifecycle import run_unified_action
from pallas.core.foundation.paths import PROJECT_ROOT

UNIFIED_SCRIPT = PROJECT_ROOT / "scripts" / "run_unified_bot.sh"
SHARD_SCRIPT = PROJECT_ROOT / "scripts" / "run_sharded_bot.sh"


def script_for_mode(mode: str) -> Path:
    return SHARD_SCRIPT if mode == "shard" else UNIFIED_SCRIPT


def bot_lifecycle_available() -> bool:
    return True


def shard_lifecycle_available() -> bool:
    return True


def run_bot_lifecycle(
    action: str,
    *,
    mode: str = "auto",
    extra_args: Sequence[str] | None = None,
) -> int:
    resolved = resolve_bot_mode(mode)
    extra = list(extra_args or ())
    if resolved == "unified":
        skip_port_sync = action == "restart" or "--skip-port-sync" in extra
        detach = "--detach" in extra
        return run_unified_action(action, skip_port_sync=skip_port_sync, detach=detach)
    return run_shard_action(action, extra_args=extra)


def restart_after_delay(delay_s: float, mode: str, workers_only: bool) -> None:
    time.sleep(delay_s)
    extra: list[str] = []
    if workers_only and mode == "shard":
        extra.append("--workers-only")
    raise SystemExit(run_bot_lifecycle("restart", mode=mode, extra_args=extra))


def schedule_bot_restart(
    *,
    mode: str = "auto",
    workers_only: bool = False,
    delay_s: float = 2.0,
) -> bool:
    try:
        from packages.pb_webui.api import invalidate_health_snapshot
        from packages.pb_webui.restart_state import mark_restart_requested

        mark_restart_requested(workers_only=workers_only)
        invalidate_health_snapshot()
    except Exception:
        pass
    resolved = resolve_bot_mode(mode)
    py = (
        "from pallas.console.cli.bot_process import restart_after_delay; "
        f"restart_after_delay({delay_s!r}, {resolved!r}, {workers_only!r})"
    )
    try:
        spawn_detached(
            [sys.executable, "-c", py],
            cwd=PROJECT_ROOT,
        )
    except OSError:
        return False
    return True
