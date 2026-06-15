"""Hub：注册表需要更多生产 worker 时，自动执行 start --workers-only。"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import TYPE_CHECKING

from src.foundation.config.repo_settings import repo_root
from src.foundation.paths import PROJECT_ROOT, plugin_data_dir
from src.platform.shard.registry.config import get_shard_registry_settings
from src.platform.shard.registry.store import ShardRegistry, get_shard_registry
from src.platform.shard.registry.worker_count import calc_production_worker_count

if TYPE_CHECKING:
    from pathlib import Path

_PLUGIN = "pallas_shard"
_RUN_SUBDIR = "run"
_SCALE_LOCK = "worker_scale.lock"
_DEBOUNCE_SEC = 5.0

_lock = threading.Lock()
_debounce_timer: threading.Timer | None = None
_scaling = False


def auto_scale_workers_enabled() -> bool:
    raw = (os.environ.get("PALLAS_SHARD_AUTO_SCALE_WORKERS") or "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def shard_run_dir() -> Path:
    return plugin_data_dir(_PLUGIN) / _RUN_SUBDIR


def production_worker_count_required(reg: ShardRegistry | None = None) -> int:
    reg = reg or get_shard_registry()
    accounts = PROJECT_ROOT / "data/pallas_protocol/accounts.json"
    return calc_production_worker_count(
        bots_per_shard=reg.bots_per_shard,
        worker_base_port=reg.worker_base_port,
        accounts_path=accounts if accounts.is_file() else None,
        registry=reg,
    )


def pid_is_alive(pid_file: Path) -> bool:
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def list_running_production_worker_shard_ids() -> set[int]:
    run_dir = shard_run_dir()
    if not run_dir.is_dir():
        return set()
    running: set[int] = set()
    for pid_file in run_dir.glob("worker-*.pid"):
        stem = pid_file.stem
        if stem == "worker-test":
            continue
        suffix = stem.removeprefix("worker-")
        if suffix == stem:
            continue
        try:
            sid = int(suffix)
        except ValueError:
            continue
        if pid_is_alive(pid_file):
            running.add(sid)
    return running


def workers_need_scale_up(reg: ShardRegistry | None = None) -> tuple[bool, int, int]:
    """返回 (需要扩容, 应有 worker 数, 当前运行 worker 数)。"""
    required = production_worker_count_required(reg)
    running_ids = list_running_production_worker_shard_ids()
    running_count = len(running_ids)
    if running_count <= 0:
        return False, required, running_count
    missing = missing_production_worker_shard_ids(reg)
    return bool(missing), required, running_count


def missing_production_worker_shard_ids(reg: ShardRegistry | None = None) -> set[int]:
    required = production_worker_count_required(reg)
    running = list_running_production_worker_shard_ids()
    return set(range(required)) - running


def schedule_worker_scale_restart(*, reason: str = "", delay_sec: float = _DEBOUNCE_SEC) -> bool:
    """Hub 进程：防抖后后台 start --workers-only；非 hub 或无需扩容时跳过。"""
    settings = get_shard_registry_settings()
    if not settings.enabled or settings.role != "hub" or not auto_scale_workers_enabled():
        return False
    need, _, _ = workers_need_scale_up()
    if not need:
        return False

    global _debounce_timer

    def fire() -> None:
        run_worker_scale_restart(reason=reason)

    with _lock:
        if _debounce_timer is not None:
            _debounce_timer.cancel()
        _debounce_timer = threading.Timer(delay_sec, fire)
        _debounce_timer.daemon = True
        _debounce_timer.start()
    return True


def run_worker_scale_restart(*, reason: str = "") -> bool:
    """立即尝试扩容 worker。"""
    settings = get_shard_registry_settings()
    if not settings.enabled or settings.role != "hub" or not auto_scale_workers_enabled():
        return False

    need, required, running = workers_need_scale_up()
    if not need:
        return False

    global _scaling
    with _lock:
        if _scaling:
            return False
        _scaling = True

    lock_path = shard_run_dir() / _SCALE_LOCK
    missing = sorted(missing_production_worker_shard_ids())
    try:
        return execute_workers_only_start(
            reason=reason,
            required=required,
            running=running,
            missing_shard_ids=missing,
            lock_path=lock_path,
        )
    finally:
        with _lock:
            _scaling = False


def execute_workers_only_start(
    *,
    reason: str,
    required: int,
    running: int,
    missing_shard_ids: list[int],
    lock_path: Path,
) -> bool:
    from nonebot import logger

    shard_run_dir().mkdir(parents=True, exist_ok=True)
    if lock_path.is_file():
        try:
            if time.time() - lock_path.stat().st_mtime < 120.0:
                logger.info(
                    "shard worker scale: skip (lock active) reason={} required={} running={}",
                    reason,
                    required,
                    running,
                )
                return False
        except OSError:
            pass
        lock_path.unlink(missing_ok=True)

    script = repo_root() / "scripts" / "run_sharded_bot.sh"
    if not script.is_file():
        logger.warning("shard worker scale: missing script {}", script)
        return False

    try:
        lock_path.write_text(f"pid={os.getpid()} ts={time.time():.0f}\n", encoding="utf-8")
    except OSError as err:
        logger.warning("shard worker scale: lock write failed: {}", err)
        return False

    logger.info(
        "shard worker scale: start --workers-only reason={} required={} running={} missing={}",
        reason,
        required,
        running,
        missing_shard_ids,
    )
    try:
        proc = subprocess.Popen(  # noqa: S603
            ["/bin/bash", str(script), "start", "--workers-only", "--scale-only"],
            cwd=str(repo_root()),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as err:
        logger.warning("shard worker scale: spawn failed: {}", err)
        lock_path.unlink(missing_ok=True)
        return False

    def reap() -> None:
        try:
            _, stderr = proc.communicate(timeout=600)
            if proc.returncode != 0:
                tail = (stderr or b"").decode("utf-8", errors="replace").strip()[-500:]
                logger.warning(
                    "shard worker scale: start exit={} stderr_tail={}",
                    proc.returncode,
                    tail,
                )
            else:
                logger.info("shard worker scale: start completed")
        except subprocess.TimeoutExpired:
            logger.warning("shard worker scale: start timed out after 600s")
        except Exception as err:
            logger.warning("shard worker scale: start wait failed: {}", err)
        finally:
            lock_path.unlink(missing_ok=True)

    threading.Thread(target=reap, name="shard-worker-scale-reap", daemon=True).start()
    return True
