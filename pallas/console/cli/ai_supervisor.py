"""托管 AI Runtime：通过 AI 仓 scripts/ctl.sh 启停与状态探测。"""

from __future__ import annotations

import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from pallas.console.cli.ai_ops import managed_ai_root, resolve_ai_repo_root
from pallas.console.webui.ai_install_writeback import DEFAULT_AI_SERVER_PORT

MANAGED_MARKER_NAME = ".pallas-managed"
_CTL = "scripts/ctl.sh"
_SERVICES = ("llm", "media", "api")


def mark_ai_root_managed(ai_root: Path) -> None:
    root = ai_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / MANAGED_MARKER_NAME).write_text("managed-by=pallas-bot\n", encoding="utf-8")


def is_managed_ai_root(ai_root: Path | None) -> bool:
    if ai_root is None:
        return False
    root = ai_root.resolve()
    if (root / MANAGED_MARKER_NAME).is_file():
        return True
    try:
        return root == managed_ai_root()
    except OSError:
        return False


def ai_root_layout(ai_root: Path | None) -> str:
    if ai_root is None:
        return "missing"
    override = os.environ.get("PALLAS_AI_ROOT", "").strip()
    if override:
        try:
            if Path(override).expanduser().resolve() == ai_root.resolve():
                return "env"
        except OSError:
            pass
    if is_managed_ai_root(ai_root):
        return "managed"
    return "sibling"


def _pidfile(ai_root: Path, service: str) -> Path:
    return ai_root / "logs" / f"{service}.pid"


def _read_pid(pidfile: Path) -> int | None:
    if not pidfile.is_file():
        return None
    try:
        raw = pidfile.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw.isdigit():
        return None
    return int(raw)


def _pid_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def service_running(ai_root: Path, service: str) -> bool:
    return _pid_alive(_read_pid(_pidfile(ai_root, service)))


def resolve_ai_listen_port(ai_root: Path | None = None) -> int:
    root = ai_root or resolve_ai_repo_root()
    if root is not None:
        env_path = root / ".env"
        if env_path.is_file():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    if line.startswith("UVICORN_PORT="):
                        raw = line.split("=", 1)[1].strip().strip("\"'")
                        if raw.isdigit():
                            return int(raw)
            except OSError:
                pass
    _, port = resolve_configured_ai_endpoint()
    return port


def running_in_docker() -> bool:
    return Path("/.dockerenv").is_file()


def is_loopback_host(host: str) -> bool:
    h = str(host or "").strip().lower()
    return h in {"", "127.0.0.1", "localhost", "::1"}


def resolve_configured_ai_endpoint() -> tuple[str, int]:
    """媒体 / 兼容路径探测目标：AI_SERVER_* → extension base_url → 127.0.0.1:9099。"""
    from pallas.core.foundation.config.repo_settings import repo_env_raw_value

    host = (repo_env_raw_value("AI_SERVER_HOST") or "").strip()
    port_raw = (repo_env_raw_value("AI_SERVER_PORT") or "").strip()
    if host:
        port = int(port_raw) if port_raw.isdigit() else int(DEFAULT_AI_SERVER_PORT)
        return host, port

    try:
        from pallas.console.webui.ai_install_writeback import (
            ai_extension_config_path,
            parse_ai_server_from_base_url,
        )

        cfg_path = ai_extension_config_path()
        if cfg_path.is_file():
            import json

            loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                parsed = parse_ai_server_from_base_url(str(loaded.get("base_url") or ""))
                if parsed is not None:
                    return parsed[0], int(parsed[1])
    except Exception:  # noqa: BLE001
        pass
    return "127.0.0.1", int(DEFAULT_AI_SERVER_PORT)


def probe_ai_health_at(host: str, port: int, *, timeout_sec: float = 3.0) -> dict[str, Any]:
    h = str(host or "").strip() or "127.0.0.1"
    url = f"http://{h}:{int(port)}/health"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read(4096).decode("utf-8", errors="replace")
            return {
                "ok": 200 <= int(resp.status) < 300,
                "url": url,
                "status_code": int(resp.status),
                "body_preview": body[:500],
                "error": None,
            }
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "url": url,
            "status_code": int(exc.code),
            "body_preview": None,
            "error": str(exc),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "url": url,
            "status_code": None,
            "body_preview": None,
            "error": str(exc),
        }


def probe_ai_health_sync(*, ai_root: Path | None = None, timeout_sec: float = 3.0) -> dict[str, Any]:
    if ai_root is not None:
        port = resolve_ai_listen_port(ai_root)
        return probe_ai_health_at("127.0.0.1", port, timeout_sec=timeout_sec)
    host, port = resolve_configured_ai_endpoint()
    return probe_ai_health_at(host, port, timeout_sec=timeout_sec)


def remote_runtime_layout(host: str) -> str:
    if running_in_docker() or not is_loopback_host(host):
        return "docker"
    return "remote"


def ai_runtime_status(*, ai_root: Path | None = None) -> dict[str, Any]:
    root = ai_root if ai_root is not None else resolve_ai_repo_root()
    if root is None:
        host, port = resolve_configured_ai_endpoint()
        health = probe_ai_health_at(host, port)
        if health.get("ok"):
            layout = remote_runtime_layout(host)
        elif running_in_docker() or not is_loopback_host(host):
            layout = "docker"
        else:
            layout = "missing"
        return {
            "can_manage": False,
            "ai_root": None,
            "layout": layout,
            "running": bool(health.get("ok")),
            "endpoint": {"host": host, "port": port},
            "services": {name: {"running": False, "pid": None} for name in _SERVICES},
            "health": health,
        }

    services: dict[str, dict[str, Any]] = {}
    for name in _SERVICES:
        pid = _read_pid(_pidfile(root, name))
        running = _pid_alive(pid)
        services[name] = {"running": running, "pid": pid if running else None}

    api_up = bool(services["api"]["running"])
    llm_up = bool(services["llm"]["running"])
    health = (
        probe_ai_health_sync(ai_root=root)
        if api_up
        else {
            "ok": False,
            "url": f"http://127.0.0.1:{resolve_ai_listen_port(root)}/health",
            "status_code": None,
            "body_preview": None,
            "error": "api 未运行",
        }
    )
    ctl_ready = (root / _CTL).is_file()
    return {
        "can_manage": ctl_ready,
        "ai_root": str(root),
        "layout": ai_root_layout(root),
        "running": api_up and llm_up,
        "endpoint": {"host": "127.0.0.1", "port": resolve_ai_listen_port(root)},
        "services": services,
        "health": health,
    }


def run_ctl(ai_root: Path, *args: str, timeout_sec: float = 120.0) -> tuple[int, str]:
    script = ai_root / _CTL
    if not script.is_file():
        return 1, f"未找到 {script}"
    cmd = ["bash", str(script), *args]
    completed = subprocess.run(
        cmd,
        cwd=ai_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
    )
    out = (completed.stdout or "") + (completed.stderr or "")
    header = f"执行: {' '.join(cmd)}\n"
    return int(completed.returncode), header + out


def start_ai_runtime(*, ai_root: Path | None = None, with_media: bool = False) -> dict[str, Any]:
    root = ai_root or resolve_ai_repo_root()
    if root is None:
        return {"ok": False, "error": "未检测到本地 AI Runtime，Docker 请在宿主机启停容器", "output_tail": ""}
    outputs: list[str] = []
    if with_media:
        code, out = run_ctl(root, "start", "all")
        outputs.append(out)
        if code != 0:
            return {"ok": False, "error": f"ctl start all 退出码 {code}", "output_tail": out[-8000:]}
    else:
        for target in ("llm", "api"):
            code, out = run_ctl(root, "start", target)
            outputs.append(out)
            if code != 0:
                return {
                    "ok": False,
                    "error": f"ctl start {target} 退出码 {code}",
                    "output_tail": "\n".join(outputs)[-8000:],
                }
    if is_managed_ai_root(root):
        mark_ai_root_managed(root)
    status = ai_runtime_status(ai_root=root)
    return {
        "ok": True,
        "error": None,
        "output_tail": "\n".join(outputs)[-8000:],
        "runtime": status,
    }


def stop_ai_runtime(*, ai_root: Path | None = None) -> dict[str, Any]:
    root = ai_root or resolve_ai_repo_root()
    if root is None:
        return {"ok": False, "error": "未检测到本地 AI Runtime", "output_tail": ""}
    code, out = run_ctl(root, "stop", "all")
    status = ai_runtime_status(ai_root=root)
    return {
        "ok": code == 0,
        "error": None if code == 0 else f"ctl stop all 退出码 {code}",
        "output_tail": out[-8000:],
        "runtime": status,
    }
