"""托管 MaiBot 源码实例：只读预检、受控启动、就绪门与可核实所有权的优雅停止。

只支持维护者已安装依赖、已在前台完成协议确认的本机源码实例；不下载/安装、
不写实例配置、不注入协议同意或升级绕过环境变量。开启托管必须同时开启有效桥，
且桥地址为本机明文 ``ws://loopback:port/ws``，与实例 ``[maim_message]`` 监听端口一致。
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from pallas.console.cli.process_util import (
    clear_pid_file,
    env_for_nested_project,
    group_has_live_member,
    is_windows,
    pid_alive,
    read_pid_file,
    report_process_stop,
    spawn_detached,
    stop_pid,
    write_pid_file,
)
from pallas.core.foundation.config.repo_settings import repo_env_raw_value
from pallas.core.foundation.paths import PROJECT_ROOT

MANAGED_ENABLED_KEY = "MAIBOT_MANAGED_ENABLED"
MANAGED_DIR_KEY = "MAIBOT_MANAGED_DIR"
MANAGED_PYTHON_KEY = "MAIBOT_MANAGED_PYTHON"

RUN_DIR = PROJECT_ROOT / "data" / "pallas_maibot" / "run"
LOG_DIR = PROJECT_ROOT / "data" / "pallas_maibot" / "logs"
PID_FILE = RUN_DIR / "maibot.pid"
OWNER_FILE = RUN_DIR / "maibot.owner.json"
LOG_FILE = LOG_DIR / "maibot.log"

READY_TIMEOUT_S = 60.0
READY_POLL_INTERVAL_S = 0.25
STOP_GRACE_S = 55.0

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
_DROP_ENV = (
    "PYTHONPATH",
    "MAIBOT_WORKER_PROCESS",
    "MAIBOT_INSTANCE_DIR",
    "EULA_AGREE",
    "PRIVACY_AGREE",
    "MAIBOT_LEGACY_0X_UPGRADE_CONFIRMED",
)


class ManagedConfigError(RuntimeError):
    """托管配置显式开启但不可用。"""


@dataclass(frozen=True)
class ManagedMaiBotConfig:
    enabled: bool = False
    instance_dir: Path | None = None
    python: Path | None = None


@dataclass(frozen=True)
class ManagedStartResult:
    rc: int
    spawned_pid: int | None = None


def _parse_enabled(raw: object) -> bool:
    if raw is None:
        return False
    text = str(raw).strip().lower()
    if not text:
        return False
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    raise ManagedConfigError(f"{MANAGED_ENABLED_KEY} 必须是布尔值")


def _resolve_dir_under_project(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _resolve_path_under_project(raw: str) -> Path:
    # 解释器路径不 resolve：保留 .venv/bin/python 符号链接语义
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def default_managed_python(instance_dir: Path) -> Path:
    if is_windows():
        return instance_dir / ".venv" / "Scripts" / "python.exe"
    return instance_dir / ".venv" / "bin" / "python"


def load_managed_config() -> ManagedMaiBotConfig:
    enabled = _parse_enabled(repo_env_raw_value(MANAGED_ENABLED_KEY))
    if not enabled:
        return ManagedMaiBotConfig(enabled=False)
    dir_raw = str(repo_env_raw_value(MANAGED_DIR_KEY) or "").strip()
    if not dir_raw:
        raise ManagedConfigError(f"开启托管需配置 {MANAGED_DIR_KEY}")
    instance_dir = _resolve_dir_under_project(dir_raw)
    python_raw = str(repo_env_raw_value(MANAGED_PYTHON_KEY) or "").strip()
    python = _resolve_path_under_project(python_raw) if python_raw else default_managed_python(instance_dir)
    return ManagedMaiBotConfig(enabled=True, instance_dir=instance_dir, python=python)


def maibot_aux_running() -> bool:
    pid = read_pid_file(PID_FILE)
    return pid is not None and pid_alive(pid)


# ---------------------------------------------------------------- url / host


def _is_loopback(host: str | None) -> bool:
    return (host or "").strip().lower() in ("127.0.0.1", "localhost", "::1")


def bridge_host_port(url: str) -> tuple[str, int] | None:
    """严格解析：仅 ``ws://<loopback>:port/ws``，无 userinfo/query/fragment；失败返回 None。

    loopback 仅限 ``127.0.0.1`` / ``localhost`` / ``::1``；``0.0.0.0`` / ``::`` 是监听地址，
    不作可连接桥地址。
    """
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "ws":
            return None
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            return None
        if parsed.path != "/ws":
            return None
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if host is None or port is None or not (1 <= port <= 65535):
        return None
    if not _is_loopback(host):
        return None
    return host, port


def _host_families(host: str | None) -> frozenset[str]:
    text = (host or "").strip().lower()
    if text in ("127.0.0.1", "0.0.0.0"):
        return frozenset({"ipv4"})
    if text in ("::1", "::", "[::]"):
        return frozenset({"ipv6"})
    if text == "localhost":
        return frozenset({"ipv4", "ipv6"})
    return frozenset()


def _load_bridge():
    from pallas.product.agent_bridge.config import BridgeConfigError, load_bridge_config

    try:
        return load_bridge_config(), None
    except BridgeConfigError as exc:
        return None, str(exc)


# ---------------------------------------------------------------- preflight


def _md5_text(path: Path) -> str:
    return hashlib.md5(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def _safe_toml(path: Path, problems: list[str]) -> dict | None:
    if not path.is_file():
        problems.append(f"缺少配置 {path}")
        return None
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        problems.append(f"配置不是有效 TOML：{path}")
        return None
    return data if isinstance(data, dict) else None


def _protocol_problems(instance_dir: Path) -> list[str]:
    problems: list[str] = []
    for doc_name, confirm_name in (("EULA.md", "eula.confirmed"), ("PRIVACY.md", "privacy.confirmed")):
        doc = instance_dir / doc_name
        confirm = instance_dir / confirm_name
        if not doc.is_file():
            problems.append(f"缺少协议文件 {doc}")
            continue
        if not confirm.is_file():
            problems.append(f"未确认协议：缺少 {confirm}（请先在实例目录前台完成确认）")
            continue
        try:
            matched = _md5_text(doc) == confirm.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            problems.append(f"无法读取协议文件（编码异常）：{doc_name}")
            continue
        if not matched:
            problems.append(f"协议已变更：{confirm} 与当前 {doc_name} 不一致（请先在前台重新确认）")
    return problems


def validate_managed_instance(config: ManagedMaiBotConfig, bridge) -> list[str]:
    """只读预检；返回问题列表（空表示可启动），不回显桥地址原文。"""
    problems: list[str] = []
    if config.instance_dir is None or config.python is None:
        return ["托管配置未解析实例目录/解释器"]
    instance_dir = config.instance_dir
    if not instance_dir.is_dir():
        problems.append(f"实例目录不存在：{instance_dir}")
    elif not (instance_dir / "bot.py").is_file():
        problems.append(f"缺少实例入口 bot.py：{instance_dir / 'bot.py'}")
    if not config.python.is_file():
        problems.append(f"缺少独立解释器：{config.python}")
    elif not os.access(config.python, os.X_OK):
        problems.append(f"解释器不可执行：{config.python}")

    bot_data = _safe_toml(instance_dir / "config" / "bot_config.toml", problems)
    _safe_toml(instance_dir / "config" / "model_config.toml", problems)

    bridge_addr = bridge_host_port(bridge.url)
    if bridge_addr is None:
        problems.append("桥地址必须是本机明文 ws://loopback:port/ws（仅 /ws 路径、无 userinfo/query）")
    if bot_data is not None:
        maim = bot_data.get("maim_message")
        maim = maim if isinstance(maim, dict) else {}
        host = str(maim.get("ws_server_host", "127.0.0.1"))
        port = maim.get("ws_server_port", 8000)
        inst_families = _host_families(host)
        if not inst_families:
            problems.append("实例 maim_message.ws_server_host 不是本机地址")
        elif bridge_addr is not None and not (inst_families & _host_families(bridge_addr[0])):
            problems.append("桥与实例监听不在同一 address family（IPv4/IPv6 不匹配）")
        if not isinstance(port, int) or isinstance(port, bool):
            problems.append("实例 maim_message.ws_server_port 不是整数")
        elif bridge_addr is not None and bridge_addr[1] != port:
            problems.append(f"桥端口 {bridge_addr[1]} 与实例 ws_server_port {port} 不一致")

    problems.extend(_protocol_problems(instance_dir))
    return problems


def build_managed_env(instance_dir: Path) -> dict[str, str]:
    env = env_for_nested_project()
    for key in _DROP_ENV:
        env.pop(key, None)
    env["MAIBOT_INSTANCE_DIR"] = str(instance_dir)
    env["PYTHONUNBUFFERED"] = "1"
    return env


# ---------------------------------------------------------------- ownership


def _proc_starttime(pid: int) -> str | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        fields = raw.rsplit(")", 1)[1].split()
        return fields[19]  # starttime = field 22 (1-based); after comm/state offset
    except (IndexError, ValueError):
        return None


def _proc_cwd(pid: int) -> str | None:
    try:
        return str(Path(f"/proc/{pid}/cwd").readlink())
    except OSError:
        return None


def _proc_boot_id() -> str | None:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        return None


def linux_managed_supported() -> bool:
    """托管所有权核实依赖 Linux ``/proc``（starttime/cwd/boot_id）；否则 fail-closed。"""
    return not is_windows() and _proc_starttime(os.getpid()) is not None and _proc_boot_id() is not None


def _read_owner() -> dict | None:
    try:
        data = json.loads(OWNER_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_owner(pid: int, instance_dir: Path) -> None:
    OWNER_FILE.parent.mkdir(parents=True, exist_ok=True)
    OWNER_FILE.write_text(
        json.dumps({
            "pid": pid,
            "instance_dir": str(instance_dir),
            "starttime": _proc_starttime(pid),
            "boot_id": _proc_boot_id(),
        }),
        encoding="utf-8",
    )


def _clear_owner() -> None:
    try:
        OWNER_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def current_managed_process() -> int | None:
    """返回已核实身份的受管 pid；无法核实（含非 Linux / 读不到 cwd/starttime）返回 None。"""
    if not linux_managed_supported():
        return None
    pid = read_pid_file(PID_FILE)
    if pid is None or not pid_alive(pid):
        return None
    owner = _read_owner()
    if owner is None or owner.get("pid") != pid:
        return None
    boot_id = _proc_boot_id()
    if not boot_id or str(owner.get("boot_id") or "") != boot_id:
        return None
    recorded = owner.get("starttime")
    actual = _proc_starttime(pid)
    if not recorded or not actual or str(recorded) != str(actual):
        return None
    instance_dir = owner.get("instance_dir")
    cwd = _proc_cwd(pid)
    if not instance_dir or cwd is None:
        return None
    if Path(str(instance_dir)).resolve() != Path(cwd).resolve():
        return None
    return pid


def managed_runtime_state() -> str:
    """off | invalid | running | not_running。"""
    try:
        config = load_managed_config()
    except ManagedConfigError:
        return "invalid"
    if not config.enabled:
        return "off"
    if current_managed_process() is not None:
        return "running"
    return "not_running"


# ---------------------------------------------------------------- process ops


def _port_connectable(host: str, port: int, *, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _stop_owned_pid(pid: int, *, force: bool = False) -> bool:
    """停止本进程 spawn 的 pid（``spawn_detached`` 用 ``start_new_session``，pgid==pid）。

    委托 ``process_util.stop_pid(wait_for_group=True)``：TERM→有界等待全组→KILL，
    仍有非僵尸成员时返回 False（不宣称已停止）。
    """
    return stop_pid(pid, timeout_s=STOP_GRACE_S, force=force, wait_for_group=True)


def stop_spawned_pid(pid: int) -> bool:
    """回滚本次 spawn 的 pid（不读 pid 文件盲停）；返回是否已确认停止。"""
    if pid <= 0:
        return True
    ok = _stop_owned_pid(pid)
    if read_pid_file(PID_FILE) == pid and ok:
        clear_pid_file(PID_FILE)
        _clear_owner()
    return ok


def _print_problems(problems: list[str]) -> None:
    for problem in problems:
        print(f"  · MaiBot 托管：{problem}", file=sys.stderr)


def _wait_transport_ready(host: str, port: int, *, timeout_s: float, owned_pid: int | None) -> int:
    deadline = time.monotonic() + timeout_s
    while True:
        if owned_pid is not None and not pid_alive(owned_pid):
            print("  · MaiBot 托管：进程已退出，未就绪", file=sys.stderr)
            return 1
        if _port_connectable(host, port) and (owned_pid is None or pid_alive(owned_pid)):
            print("  · MaiBot 托管：消息端口可连接（transport ready，不代表模型/插件健康）")
            return 0
        if time.monotonic() >= deadline:
            print("  · MaiBot 托管：等待消息端口就绪超时", file=sys.stderr)
            return 1
        time.sleep(READY_POLL_INTERVAL_S)


def _rollback_spawn(pid: int | None) -> None:
    if pid is not None and not _stop_owned_pid(pid):
        print("  · MaiBot 托管：回滚未清理同组残留，保留记录（请手动处理）", file=sys.stderr)
        return
    clear_pid_file(PID_FILE)
    _clear_owner()


def start_maibot_aux(*, dry_run: bool = False, ready_timeout_s: float = READY_TIMEOUT_S) -> ManagedStartResult:
    try:
        config = load_managed_config()
    except ManagedConfigError as exc:
        print(f"  · MaiBot 托管：配置无效：{exc}", file=sys.stderr)
        return ManagedStartResult(rc=1)
    if not config.enabled:
        return ManagedStartResult(rc=0)

    bridge, bridge_error = _load_bridge()
    if bridge is None:
        print(f"  · MaiBot 托管：桥配置无效：{bridge_error}", file=sys.stderr)
        return ManagedStartResult(rc=1)
    if not bridge.enabled:
        print("  · MaiBot 托管：桥未启用，拒绝托管（请先配置 MAIBOT_BRIDGE_ENABLED）", file=sys.stderr)
        return ManagedStartResult(rc=1)

    problems = validate_managed_instance(config, bridge)
    if problems:
        _print_problems(problems)
        return ManagedStartResult(rc=1)

    addr = bridge_host_port(bridge.url)
    assert addr is not None  # validate_managed_instance ensured it
    host, port = addr

    owned = current_managed_process()
    if owned is not None:
        print(f"  · MaiBot 托管：已在运行 pid={owned}")
        return ManagedStartResult(rc=_wait_transport_ready(host, port, timeout_s=ready_timeout_s, owned_pid=owned))
    if maibot_aux_running():
        print("  · MaiBot 托管：检测到 pid 存活但无法核实身份，拒绝接管（请手动处理）", file=sys.stderr)
        return ManagedStartResult(rc=1)
    if dry_run:
        print("  · MaiBot 托管：将启动（预览）")
        return ManagedStartResult(rc=0)
    if _port_connectable(host, port):
        print(
            f"  · MaiBot 托管：消息端口 {host}:{port} 已被占用，拒绝启动（可能是外部实例，请先处理）",
            file=sys.stderr,
        )
        return ManagedStartResult(rc=1)

    assert config.instance_dir is not None
    assert config.python is not None
    if not linux_managed_supported():
        print("  · MaiBot 托管：仅支持 Linux 且 /proc 可读，拒绝启动", file=sys.stderr)
        return ManagedStartResult(rc=1)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [str(config.python), "-u", "bot.py"]
    env = build_managed_env(config.instance_dir)
    spawned_pid: int | None = None
    try:
        spawned_pid = spawn_detached(
            cmd,
            cwd=config.instance_dir,
            env=env,
            log_path=LOG_FILE,
            inherit_env=False,
        )
        write_pid_file(PID_FILE, spawned_pid)
        _write_owner(spawned_pid, config.instance_dir)
        if current_managed_process() != spawned_pid:
            print("  · MaiBot 托管：无法建立受管进程身份，回滚", file=sys.stderr)
            _rollback_spawn(spawned_pid)
            return ManagedStartResult(rc=1)
        rc = _wait_transport_ready(host, port, timeout_s=ready_timeout_s, owned_pid=spawned_pid)
    except OSError as exc:
        print(f"  · MaiBot 托管：启动失败：{exc}", file=sys.stderr)
        _rollback_spawn(spawned_pid)
        return ManagedStartResult(rc=1)
    except BaseException:
        _rollback_spawn(spawned_pid)
        raise
    if rc != 0:
        _rollback_spawn(spawned_pid)
        return ManagedStartResult(rc=1)
    print(f"  · MaiBot 托管：已启动 pid={spawned_pid} 日志 {LOG_FILE}")
    return ManagedStartResult(rc=0, spawned_pid=spawned_pid)


def _has_unresolved_orphan_group() -> bool:
    """记录在案的受管 pid（同一 boot）leader 已退出但同组仍有存活成员。"""
    recorded = read_pid_file(PID_FILE)
    if recorded is None:
        return False
    owner = _read_owner()
    if owner is None or owner.get("pid") != recorded:
        return False
    boot_id = _proc_boot_id()
    if not boot_id or str(owner.get("boot_id") or "") != boot_id:
        return False
    return group_has_live_member(recorded)


def stop_maibot_aux(*, force: bool = False) -> bool:
    """停止已核实身份的受管实例；返回是否已确认停止（同组残留未清则 False，保留记录）。"""
    owned = current_managed_process()
    if owned is None:
        if _has_unresolved_orphan_group():
            print(
                "  · MaiBot 托管：leader 已退出但同组仍有存活成员，未解决孤组，保留记录（请手动处理）",
                file=sys.stderr,
            )
            return False
        if maibot_aux_running():
            print("  · MaiBot 托管：pid 存活但无法核实身份，拒绝停止（请手动处理）", file=sys.stderr)
            return False
        clear_pid_file(PID_FILE)
        _clear_owner()
        print("  · MaiBot 托管：未在运行")
        return True
    started = time.monotonic()
    ok = _stop_owned_pid(owned, force=force)
    report_process_stop("maibot", owned, time.monotonic() - started)
    if not ok:
        print("  · MaiBot 托管：存在未解决的同组残留进程，保留记录（请手动处理）", file=sys.stderr)
        return False
    clear_pid_file(PID_FILE)
    _clear_owner()
    print("  · MaiBot 托管：已停止")
    return True


def print_maibot_aux_status() -> None:
    state = managed_runtime_state()
    if state == "invalid":
        print("  · MaiBot 托管：配置无效")
    elif state == "running":
        print(f"  · MaiBot 托管：运行中 pid={read_pid_file(PID_FILE)} 日志 {LOG_FILE}")
    elif state == "off":
        print("  · MaiBot 托管：未开启")
    else:
        print("  · MaiBot 托管：未运行（已开启但进程不在）")
