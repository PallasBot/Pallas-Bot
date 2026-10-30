"""受管 MaiBot 场景下的 Pallas/MaiBot 有界启停协调。"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from pallas.console.cli import maibot_aux
from pallas.console.cli.process_util import (
    clear_pid_file,
    group_has_live_member,
    pid_alive,
    read_pid_file,
    stop_pid,
    write_pid_file,
)
from pallas.core.foundation.fs_lock import atomic_write_text, interprocess_file_lock
from pallas.core.foundation.paths import PROJECT_ROOT
from pallas.core.platform.ai_callback.internal_auth import (
    INTERNAL_TOKEN_HEADER,
    PURPOSE_MAIBOT_CONTROL_V1,
    derive_internal_token,
)

if TYPE_CHECKING:
    from collections.abc import Callable

CONTROL_STATUS = "/pallas/api/internal/maibot/control/status"
CONTROL_QUIESCE = "/pallas/api/internal/maibot/control/quiesce"
CONTROL_CONTRACT = "maibot-native-control-v1"
STARTUP_TIMEOUT_S = 60.0
POLL_INTERVAL_S = 0.2
HTTP_TIMEOUT_S = 0.75
STOP_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class ManagedPaths:
    project_root: Path = PROJECT_ROOT
    run_dir: Path = PROJECT_ROOT / "data" / "pallas_unified" / "run"
    pid_file: Path = PROJECT_ROOT / "data" / "pallas_unified" / "run" / "bot.pid"
    owner_file: Path = PROJECT_ROOT / "data" / "pallas_unified" / "run" / "bot.owner.json"
    lock_file: Path = PROJECT_ROOT / "data" / "pallas_unified" / "run" / "managed.lock"
    log_file: Path = PROJECT_ROOT / "data" / "pallas_unified" / "logs" / "bot.log"


DEFAULT_PATHS = ManagedPaths()


@dataclass
class ManagedRuntime:
    paths: ManagedPaths
    process: subprocess.Popen | None
    pid: int
    port: int
    runtime_id: str
    mai_pid: int
    mai_owner: dict
    aux_started: tuple[str, ...]
    control_token: str = field(repr=False)


class ManagedLifecycleError(RuntimeError):
    """受管启动未达到可验证的组件就绪状态。"""


def _proc_identity(pid: int) -> dict | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        tail = raw.rsplit(")", 1)[1].split()
        cwd = str(Path(f"/proc/{pid}/cwd").readlink())
        command = Path(f"/proc/{pid}/cmdline").read_bytes()
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
        return {
            "starttime": tail[19],
            "cwd": cwd,
            "cmdline_sha256": hashlib.sha256(command).hexdigest(),
            "argv": [item.decode(errors="replace") for item in command.rstrip(b"\x00").split(b"\x00")],
            "boot_id": boot_id,
        }
    except (OSError, IndexError):
        return None


def _read_owner(paths: ManagedPaths) -> dict | None:
    try:
        data = json.loads(paths.owner_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _owner_matches(paths: ManagedPaths, pid: int) -> bool:
    owner = _read_owner(paths)
    current = _proc_identity(pid)
    if not pid_alive(pid) or owner is None or current is None or owner.get("pid") != pid:
        return False
    return (
        all(owner.get(key) == current[key] for key in ("starttime", "cwd", "cmdline_sha256", "boot_id"))
        and Path(current["cwd"]).resolve() == paths.project_root.resolve()
        and current["argv"] == [sys.executable, "-u", str(paths.project_root / "bot.py")]
    )


def owned_bot_pid(paths: ManagedPaths) -> int | None:
    pid = read_pid_file(paths.pid_file)
    return pid if pid is not None and _owner_matches(paths, pid) else None


def _control_status_valid(status: object, expected_runtime_id: str | None = None) -> bool:
    if not isinstance(status, dict) or status.get("ok") is not True:
        return False
    runtime_id = status.get("runtime_id")
    return (
        isinstance(runtime_id, str)
        and bool(runtime_id)
        and len(runtime_id) <= 128
        and (expected_runtime_id is None or runtime_id == expected_runtime_id)
        and status.get("contract") == CONTROL_CONTRACT
        and status.get("control_ready") is True
    )


def component_ready(status: object, *, expected_runtime_id: str, mai_pid: int) -> bool:
    if not _control_status_valid(status, expected_runtime_id):
        return False
    if not isinstance(status, dict):
        return False
    bridge = status.get("bridge_status")
    if not isinstance(bridge, dict):
        return False
    return (
        status.get("component_ready") is True
        and status.get("complete_ready") is False
        and status.get("readiness_scope") == "managed-component"
        and status.get("model_invocation_verified") is False
        and status.get("quiesced") is False
        and bridge.get("connected") is True
        and bridge.get("state") == "connected"
        and maibot_aux.current_managed_process() == mai_pid
    )


def control_request(
    port: int,
    method: str,
    path: str,
    *,
    token: str,
    body: dict | None = None,
    timeout_s: float = HTTP_TIMEOUT_S,
) -> dict | None:
    """直接访问 loopback：不读代理环境、不跟随重定向，响应限 2 KiB。"""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout_s)
    headers = {INTERNAL_TOKEN_HEADER: token, "Accept": "application/json"}
    encoded = None
    if body is not None:
        encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    try:
        conn.request(method, path, body=encoded, headers=headers)
        response = conn.getresponse()
        if response.status != 200:
            return None
        payload = response.read(2049)
        if len(payload) > 2048:
            return None
        value = json.loads(payload)
        return value if isinstance(value, dict) else None
    except (OSError, http.client.HTTPException, ValueError, json.JSONDecodeError):
        return None
    finally:
        conn.close()


def _control_status(port: int, token: str, timeout_s: float = HTTP_TIMEOUT_S) -> dict | None:
    return control_request(port, "GET", CONTROL_STATUS, token=token, timeout_s=timeout_s)


def _wait_control_ready(
    process: subprocess.Popen,
    port: int,
    token: str,
    deadline: float,
    stop_requested: Callable[[], bool],
) -> dict:
    while time.monotonic() < deadline:
        if stop_requested():
            raise ManagedLifecycleError("启动已取消")
        if process.poll() is not None:
            raise ManagedLifecycleError("Pallas 在 API 就绪前退出")
        status = _control_status(port, token, min(HTTP_TIMEOUT_S, max(0.05, deadline - time.monotonic())))
        if status is not None:
            if not _control_status_valid(status):
                if status.get("ok") is True and (
                    status.get("contract") != CONTROL_CONTRACT
                    or not isinstance(status.get("runtime_id"), str)
                    or not status.get("runtime_id")
                ):
                    raise ManagedLifecycleError("Pallas control API 契约或 runtime 不匹配")
            else:
                return status
        time.sleep(min(POLL_INTERVAL_S, max(0, deadline - time.monotonic())))
    raise ManagedLifecycleError("等待 Pallas control API 就绪超时")


def _wait_component_ready(
    process: subprocess.Popen,
    port: int,
    control_token: str,
    runtime_id: str,
    mai_pid: int,
    deadline: float,
    stop_requested: Callable[[], bool],
) -> None:
    while time.monotonic() < deadline:
        if stop_requested():
            raise ManagedLifecycleError("启动已取消")
        if process.poll() is not None:
            raise ManagedLifecycleError("Pallas 在托管组件就绪前退出")
        status = _control_status(
            port,
            control_token,
            min(HTTP_TIMEOUT_S, max(0.05, deadline - time.monotonic())),
        )
        if status is not None:
            if not _control_status_valid(status, runtime_id):
                raise ManagedLifecycleError("Pallas control runtime 在启动期间发生变化")
            if component_ready(status, expected_runtime_id=runtime_id, mai_pid=mai_pid):
                return
        time.sleep(min(POLL_INTERVAL_S, max(0, deadline - time.monotonic())))
    raise ManagedLifecycleError("等待 MaiBot 当前桥连接与进程身份就绪超时")


def _bot_env(port: int) -> dict[str, str]:
    env = dict(os.environ)
    env.update({"PALLAS_SHARD_ENABLED": "false", "PALLAS_BOT_ROLE": "unified", "PORT": str(port)})
    return env


def _spawn_pallas(paths: ManagedPaths, port: int, *, detached: bool) -> subprocess.Popen:
    kwargs: dict = {
        "args": [sys.executable, "-u", str(paths.project_root / "bot.py")],
        "cwd": str(paths.project_root),
        "env": _bot_env(port),
        "stdin": subprocess.DEVNULL if detached else None,
        "stdout": None,
        "stderr": None,
        "start_new_session": True,
    }
    if detached:
        paths.log_file.parent.mkdir(parents=True, exist_ok=True)
        log = paths.log_file.open("a", encoding="utf-8")
        kwargs["stdout"] = log
        kwargs["stderr"] = subprocess.STDOUT
        try:
            return subprocess.Popen(**kwargs)  # noqa: S603
        finally:
            log.close()
    return subprocess.Popen(**kwargs)  # noqa: S603


def _write_owner(paths: ManagedPaths, pid: int, runtime_id: str = "") -> dict:
    deadline = time.monotonic() + 2.0
    identity = _proc_identity(pid)
    while identity is None and time.monotonic() < deadline:
        time.sleep(0.02)
        identity = _proc_identity(pid)
    if identity is None:
        raise ManagedLifecycleError("无法核实 Pallas 子进程身份")
    owner = {"pid": pid, **identity, "runtime_id": runtime_id}
    write_pid_file(paths.pid_file, pid)
    try:
        atomic_write_text(paths.owner_file, json.dumps(owner, sort_keys=True), encoding="utf-8")
    except OSError:
        if read_pid_file(paths.pid_file) == pid:
            clear_pid_file(paths.pid_file)
        raise
    return owner


def _save_runtime_id(paths: ManagedPaths, owner: dict, runtime_id: str) -> dict:
    updated = {**owner, "runtime_id": runtime_id}
    atomic_write_text(paths.owner_file, json.dumps(updated, sort_keys=True), encoding="utf-8")
    return updated


def _save_mai_identity(paths: ManagedPaths, owner: dict, mai_pid: int, mai_owner: dict) -> dict:
    updated = {**owner, "mai_pid": mai_pid, "mai_owner": mai_owner}
    atomic_write_text(paths.owner_file, json.dumps(updated, sort_keys=True), encoding="utf-8")
    return updated


def _clear_records(paths: ManagedPaths, pid: int, owner: dict | None) -> bool:
    current_owner = _read_owner(paths)
    if current_owner != owner:
        return False
    recorded_pid = read_pid_file(paths.pid_file)
    if recorded_pid not in (None, pid):
        return False
    if recorded_pid == pid:
        clear_pid_file(paths.pid_file)
        if read_pid_file(paths.pid_file) is not None:
            return False
    try:
        paths.owner_file.unlink(missing_ok=True)
    except OSError:
        return False
    return not paths.owner_file.exists()


def _start_aux_tracked() -> tuple[bool, tuple[str, ...]]:
    from pallas.console.cli import embedding_aux, work_aux

    started: list[str] = []
    for name, running, start in (
        ("embed", embedding_aux.embed_aux_running, embedding_aux.start_embed_aux),
        ("work", work_aux.work_aux_running, work_aux.start_work_aux),
    ):
        was_running = running()
        try:
            rc = start()
        except Exception:
            rc = 1
        if not was_running and running():
            started.append(name)
        if rc != 0:
            return False, tuple(started)
    return True, tuple(started)


def _stop_aux_names(names: tuple[str, ...]) -> bool:
    from pallas.console.cli import embedding_aux, work_aux

    ok = True
    for name in reversed(names):
        try:
            if name == "work":
                work_aux.stop_work_aux()
                ok = ok and not work_aux.work_aux_running()
            elif name == "embed":
                embedding_aux.stop_embed_aux()
                ok = ok and not embedding_aux.embed_aux_running()
        except Exception:
            ok = False
    return ok


def _preflight(paths: ManagedPaths, port: int) -> tuple[maibot_aux.ManagedMaiBotConfig, object, str]:
    try:
        config = maibot_aux.load_managed_config()
    except maibot_aux.ManagedConfigError as exc:
        raise ManagedLifecycleError(f"托管配置无效：{exc}") from None
    if not config.enabled:
        raise ManagedLifecycleError("受管 MaiBot 未启用")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ManagedLifecycleError("Pallas API 端口无效")
    if not maibot_aux.linux_managed_supported():
        raise ManagedLifecycleError("受管生命周期需要可读的 Linux /proc")
    recorded_pid = read_pid_file(paths.pid_file)
    if recorded_pid is not None and pid_alive(recorded_pid):
        raise ManagedLifecycleError("发现已运行或身份不明的 unified Pallas，拒绝接管")
    if _read_owner(paths) is not None and read_pid_file(paths.pid_file) is None:
        raise ManagedLifecycleError("发现未配对的 Pallas 所有权记录，拒绝覆盖")
    if maibot_aux._port_connectable("127.0.0.1", port):
        raise ManagedLifecycleError("Pallas API 端口已被占用，拒绝接管")
    if (
        maibot_aux.current_managed_process() is not None
        or maibot_aux.maibot_aux_running()
        or maibot_aux._has_unresolved_orphan_group()
    ):
        raise ManagedLifecycleError("发现已运行的 MaiBot 实例，拒绝接管")

    bridge, _ = maibot_aux._load_bridge()
    if bridge is None or not bridge.enabled:
        reason = "bridge 未启用" if bridge is not None else "bridge 配置无效"
        raise ManagedLifecycleError(f"MaiBot {reason}")
    # 首次迁移在实例锁内执行；此处仅检查不依赖迁移结果的静态条件。
    problems, _ = maibot_aux._validate_static_instance(config, bridge)
    if problems:
        raise ManagedLifecycleError("MaiBot 托管预检失败：" + "；".join(problems))
    control_token = derive_internal_token(PURPOSE_MAIBOT_CONTROL_V1)
    if not control_token:
        raise ManagedLifecycleError("无法派生内部 control 凭据")
    return config, bridge, control_token


def _port_available(port: int) -> bool:
    try:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def _stop_process(pid: int, process: subprocess.Popen | None = None) -> bool:
    if pid_alive(pid) and not stop_pid(pid, timeout_s=STOP_TIMEOUT_S, wait_for_group=True):
        return False
    if process is not None:
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            return False
    return not pid_alive(pid) and not group_has_live_member(pid)


def _shutdown_locked(
    paths: ManagedPaths,
    *,
    pid: int,
    owner: dict | None,
    port: int,
    runtime_id: str,
    mai_pid: int | None,
    control_token: str,
    process: subprocess.Popen | None,
    aux_started: tuple[str, ...],
    stop_aux_all: bool,
    stop_mai: bool,
    mai_owner: dict | None = None,
) -> bool:
    errors: list[str] = []
    pallas_owned = _owner_matches(paths, pid)
    direct_child = process is not None and process.pid == pid and process.poll() is None
    control_valid = False
    if pallas_owned and runtime_id:
        status = _control_status(port, control_token)
        control_valid = _control_status_valid(status, runtime_id)
        if control_valid:
            result = control_request(port, "POST", CONTROL_QUIESCE, token=control_token)
            if not isinstance(result, dict) or result.get("ok") is not True or result.get("quiesced") is not True:
                errors.append("bridge quiesce 未确认")
        else:
            errors.append("Pallas control API runtime 未确认")
    elif pid_alive(pid):
        errors.append("Pallas control API 身份未确认")

    mai_stopped = True
    if stop_mai:
        expected_mai = mai_owner
        if expected_mai is None and owner:
            expected_mai = owner.get("mai_owner")
        current_mai = maibot_aux.current_managed_process()
        if current_mai is not None:
            if mai_pid is None or current_mai != mai_pid or not isinstance(expected_mai, dict):
                mai_stopped = False
            else:
                try:
                    mai_stopped = maibot_aux.stop_spawned_pid(current_mai, expected_owner=expected_mai)
                except Exception:
                    mai_stopped = False
        elif maibot_aux.maibot_aux_running() or maibot_aux._has_unresolved_orphan_group():
            mai_stopped = False
        if not mai_stopped:
            print("unified 停止失败：MaiBot 仍在运行或身份无法核实，保留 Pallas 与所有权记录", file=sys.stderr)
            return False

    if pid_alive(pid) and not pallas_owned and not direct_child:
        print("unified 停止失败：Pallas 进程身份已变化，拒绝停止", file=sys.stderr)
        return False
    stopped = _stop_process(pid, process)
    if stopped:
        if not _clear_records(paths, pid, owner):
            errors.append("Pallas 已停止，但所有权记录清理未确认")
    else:
        errors.append("Pallas 子进程未确认停止，保留所有权记录")

    if stopped and stop_aux_all:
        try:
            from pallas.console.cli.unified_lifecycle import stop_aux_services

            stop_aux_services()
        except Exception:
            errors.append("aux 服务停止失败")
    elif stopped and aux_started and not _stop_aux_names(aux_started):
        errors.append("本次启动的 aux 服务回滚失败")

    if errors:
        print("unified 停止/回滚未完整确认：" + "；".join(errors), file=sys.stderr)
        return False
    return stopped and mai_stopped


def start_managed_runtime(
    port: int,
    *,
    paths: ManagedPaths = DEFAULT_PATHS,
    detached: bool,
    stop_requested: Callable[[], bool],
    pre_launch: Callable[[], bool] = lambda: True,
    timeout_s: float = STARTUP_TIMEOUT_S,
) -> ManagedRuntime | None:
    process: subprocess.Popen | None = None
    owner: dict | None = None
    runtime_id = ""
    mai_pid: int | None = None
    mai_owner: dict | None = None
    aux_started: tuple[str, ...] = ()
    control_token = ""
    with interprocess_file_lock(paths.lock_file):

        def rollback_start() -> None:
            if process is None:
                if aux_started:
                    _stop_aux_names(aux_started)
                return
            _shutdown_locked(
                paths,
                pid=process.pid,
                owner=owner,
                port=port,
                runtime_id=runtime_id,
                mai_pid=mai_pid,
                control_token=control_token,
                process=process,
                aux_started=aux_started,
                stop_aux_all=False,
                stop_mai=mai_pid is not None,
                mai_owner=mai_owner,
            )

        try:
            config, bridge, control_token = _preflight(paths, port)
            if not _port_available(port):
                raise ManagedLifecycleError("Pallas API 端口不可绑定，拒绝启动")
            if stop_requested():
                raise ManagedLifecycleError("启动已取消")
            if not pre_launch():
                raise ManagedLifecycleError("unified 端口准备失败")
            if stop_requested():
                raise ManagedLifecycleError("启动已取消")
            aux_ok, aux_started = _start_aux_tracked()
            if not aux_ok:
                raise ManagedLifecycleError("Pallas aux 服务启动失败")
            if stop_requested():
                raise ManagedLifecycleError("启动已取消")
            process = _spawn_pallas(paths, port, detached=detached)
            owner = _write_owner(paths, process.pid)
            deadline = time.monotonic() + timeout_s
            status = _wait_control_ready(process, port, control_token, deadline, stop_requested)
            runtime_id = str(status["runtime_id"])
            owner = _save_runtime_id(paths, owner, runtime_id)
            if stop_requested():
                raise ManagedLifecycleError("启动已取消")
            remaining = max(0.0, deadline - time.monotonic())
            result = maibot_aux.start_maibot_aux(
                ready_timeout_s=remaining,
                stop_requested=stop_requested,
            )
            if result.rc != 0 or result.spawned_pid is None:
                raise ManagedLifecycleError("MaiBot 未由本次启动并就绪，拒绝接管")
            mai_pid = result.spawned_pid
            mai_owner = result.owner
            if not isinstance(mai_owner, dict) or mai_owner.get("pid") != mai_pid:
                raise ManagedLifecycleError("MaiBot 未返回本次启动的进程身份")
            if maibot_aux.current_managed_process() != mai_pid:
                raise ManagedLifecycleError("MaiBot OS 进程身份核实失败")
            owner = _save_mai_identity(paths, owner, mai_pid, mai_owner)
            _wait_component_ready(process, port, control_token, runtime_id, mai_pid, deadline, stop_requested)
            print("MaiBot 托管组件就绪：control API + 当前 bridge WS + MaiBot OS 进程身份；未验证真实模型调用。")
            return ManagedRuntime(
                paths=paths,
                process=process,
                pid=process.pid,
                port=port,
                runtime_id=runtime_id,
                mai_pid=mai_pid,
                mai_owner=mai_owner,
                aux_started=aux_started,
                control_token=control_token,
            )
        except (ManagedLifecycleError, OSError) as exc:
            print(f"unified managed 启动失败：{exc}", file=sys.stderr)
            rollback_start()
            return None
        except BaseException:
            rollback_start()
            raise


def wait_foreground(
    runtime: ManagedRuntime,
    *,
    stop_requested: Callable[[], bool],
    stop_signal: Callable[[], int | None],
) -> int:
    process = runtime.process
    if process is None:
        return 1
    while process.poll() is None and not stop_requested():
        time.sleep(0.1)
    received_signal = stop_signal()
    rc = process.poll()
    if read_pid_file(runtime.paths.pid_file) != runtime.pid:
        if rc is None:
            try:
                rc = process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                return 1
        return 128 + -rc if rc < 0 else rc
    with interprocess_file_lock(runtime.paths.lock_file):
        clean = _shutdown_locked(
            runtime.paths,
            pid=runtime.pid,
            owner=_read_owner(runtime.paths),
            port=runtime.port,
            runtime_id=runtime.runtime_id,
            mai_pid=runtime.mai_pid,
            control_token=runtime.control_token,
            process=process,
            aux_started=runtime.aux_started,
            stop_aux_all=False,
            stop_mai=True,
            mai_owner=runtime.mai_owner,
        )
    if received_signal is not None:
        return 128 + received_signal
    if rc is None:
        return 1
    if rc < 0:
        return 128 + -rc
    return rc if rc != 0 or clean else 1


def stop_running_managed(port: int, *, paths: ManagedPaths = DEFAULT_PATHS) -> bool:
    with interprocess_file_lock(paths.lock_file):
        pid = read_pid_file(paths.pid_file)
        owner = _read_owner(paths)
        if pid is None:
            if owner is None and maibot_aux.current_managed_process() is None:
                if maibot_aux.maibot_aux_running():
                    print("unified managed MaiBot PID 身份无法核实，拒绝停止", file=sys.stderr)
                    return False
                try:
                    if not maibot_aux.stop_maibot_aux():
                        print("unified managed MaiBot 停止未确认", file=sys.stderr)
                        return False
                    from pallas.console.cli.unified_lifecycle import stop_aux_services

                    stop_aux_services()
                except Exception:
                    print("unified managed 停止失败：aux 服务停止未确认", file=sys.stderr)
                    return False
                print("unified managed 未运行")
                return True
            print("unified managed Pallas 未运行", file=sys.stderr)
            return False
        if pid_alive(pid) and not _owner_matches(paths, pid):
            print("unified managed 拒绝停止：Pallas PID 身份无法核实", file=sys.stderr)
            return False
        if not isinstance(owner, dict) or owner.get("pid") != pid:
            print("unified managed Pallas 所有权记录缺失或不匹配，拒绝接管停止", file=sys.stderr)
            return False
        runtime_id = str(owner.get("runtime_id") or "") if owner else ""
        control_token = derive_internal_token(PURPOSE_MAIBOT_CONTROL_V1)
        if not control_token:
            print("unified managed 停止失败：无法派生内部凭据", file=sys.stderr)
            return False
        owner_mai_pid = owner.get("mai_pid") if owner else None
        mai_pid = owner_mai_pid if type(owner_mai_pid) is int else None
        return _shutdown_locked(
            paths,
            pid=pid,
            owner=owner,
            port=port,
            runtime_id=runtime_id,
            mai_pid=mai_pid,
            control_token=control_token,
            process=None,
            aux_started=(),
            stop_aux_all=True,
            stop_mai=True,
        )


def managed_status(paths: ManagedPaths, port: int) -> str:
    pid = owned_bot_pid(paths)
    if pid is None:
        return "Pallas process identity unavailable"
    owner = _read_owner(paths) or {}
    runtime_id = owner.get("runtime_id")
    token = derive_internal_token(PURPOSE_MAIBOT_CONTROL_V1)
    mai_pid = maibot_aux.current_managed_process()
    status = _control_status(port, token) if token else None
    if (
        not isinstance(runtime_id, str)
        or not runtime_id
        or mai_pid is None
        or not component_ready(status, expected_runtime_id=runtime_id, mai_pid=mai_pid)
    ):
        return "component readiness not confirmed (model invocation is not verified)"
    return (
        "component ready: authenticated control API + current bridge WS + MaiBot OS identity; "
        "model invocation unverified"
    )
