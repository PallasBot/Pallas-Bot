"""读写 AI Runtime ``.env`` 中的 CALLBACK_*，并探测 Bot 回调可达性。"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

from pallas.console.cli.ai_ops import (
    default_bot_callback_host,
    default_bot_callback_port,
    resolve_ai_repo_root,
)

if TYPE_CHECKING:
    from pathlib import Path

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0"})
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def read_ai_env_key(ai_root: Path, key: str, default: str = "") -> str:
    env_path = ai_root / ".env"
    if not env_path.is_file():
        return default
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return default
    found = default
    prefix = f"{key}="
    for line in lines:
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        if raw.startswith(prefix):
            found = raw.split("=", 1)[1].strip().strip("\"'")
    return found


def set_ai_env_key(ai_root: Path, key: str, value: str) -> None:
    if not _ENV_KEY_RE.match(key):
        raise ValueError(f"非法环境变量名: {key}")
    ai_root.mkdir(parents=True, exist_ok=True)
    env_path = ai_root / ".env"
    try:
        text = env_path.read_text(encoding="utf-8") if env_path.is_file() else ""
    except OSError as err:
        raise RuntimeError(f"无法读取 {env_path}: {err}") from err
    lines = text.splitlines()
    prefix = f"{key}="
    replaced = False
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(prefix) and not stripped.startswith("#"):
            out.append(f"{key}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        if out and out[-1].strip():
            out.append("")
        out.append(f"{key}={value}")
    payload = "\n".join(out)
    if not payload.endswith("\n"):
        payload += "\n"
    try:
        env_path.write_text(payload, encoding="utf-8")
    except OSError as err:
        raise RuntimeError(f"无法写入 {env_path}: {err}") from err


def read_callback_settings(ai_root: Path) -> tuple[str | None, int | None]:
    host = read_ai_env_key(ai_root, "CALLBACK_HOST", "").strip() or None
    port_raw = read_ai_env_key(ai_root, "CALLBACK_PORT", "").strip()
    port: int | None = None
    if port_raw.isdigit():
        p = int(port_raw)
        if 1 <= p <= 65535:
            port = p
    return host, port


def write_callback_settings(ai_root: Path, *, host: str, port: int) -> None:
    host_clean = host.strip()
    if not host_clean:
        raise ValueError("CALLBACK_HOST 不能为空")
    if not 1 <= int(port) <= 65535:
        raise ValueError("CALLBACK_PORT 须在 1–65535")
    set_ai_env_key(ai_root, "CALLBACK_HOST", host_clean)
    set_ai_env_key(ai_root, "CALLBACK_PORT", str(int(port)))


def hosts_loopback_compatible(a: str, b: str) -> bool:
    aa = (a or "").strip().lower()
    bb = (b or "").strip().lower()
    if not aa or not bb:
        return False
    if aa == bb:
        return True
    return aa in _LOOPBACK_HOSTS and bb in _LOOPBACK_HOSTS


def is_callback_aligned(
    host: str | None,
    port: int | None,
    *,
    expected_host: str,
    expected_port: int,
) -> bool | None:
    if host is None or port is None:
        return None
    return port == expected_port and hosts_loopback_compatible(host, expected_host)


def probe_bot_callback_target(
    host: str,
    port: int,
    *,
    timeout_sec: float = 2.0,
) -> dict[str, Any]:
    url = f"http://{host}:{int(port)}/pallas/api/health"
    result: dict[str, Any] = {
        "ok": False,
        "url": url,
        "status_code": None,
        "error": None,
    }
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            result["status_code"] = int(getattr(resp, "status", 0) or 0)
            result["ok"] = 200 <= result["status_code"] < 300
            if not result["ok"]:
                result["error"] = f"HTTP {result['status_code']}"
    except urllib.error.HTTPError as err:
        result["status_code"] = int(err.code)
        result["ok"] = False
        result["error"] = f"HTTP {err.code}"
    except Exception as err:  # noqa: BLE001
        result["error"] = str(err).strip() or err.__class__.__name__
    return result


def build_callback_status(*, ai_root: Path | None = None) -> dict[str, Any]:
    root = ai_root if ai_root is not None else resolve_ai_repo_root()
    expected_host = default_bot_callback_host()
    expected_port = default_bot_callback_port()
    base: dict[str, Any] = {
        "can_edit": False,
        "host": None,
        "port": None,
        "expected_host": expected_host,
        "expected_port": expected_port,
        "aligned": None,
        "probe": None,
        "error": None,
    }
    if root is None:
        base["error"] = "未检测到本地 AI Runtime"
        return base
    env_path = root / ".env"
    base["can_edit"] = True
    if not env_path.is_file():
        base["error"] = "AI Runtime 尚无 .env（请先 bootstrap）"
        return base
    host, port = read_callback_settings(root)
    base["host"] = host
    base["port"] = port
    base["aligned"] = is_callback_aligned(
        host,
        port,
        expected_host=expected_host,
        expected_port=expected_port,
    )
    if host and port is not None:
        base["probe"] = probe_bot_callback_target(host, port)
    else:
        base["error"] = base["error"] or "CALLBACK_HOST / CALLBACK_PORT 未配置"
    return base


def apply_callback_settings(
    *,
    ai_root: Path | None = None,
    host: str | None = None,
    port: int | None = None,
    align: bool = False,
    restart_media: bool = True,
) -> dict[str, Any]:
    from pallas.console.cli.ai_supervisor import ai_runtime_status, run_ctl

    root = ai_root if ai_root is not None else resolve_ai_repo_root()
    if root is None:
        return {
            "ok": False,
            "error": "未检测到本地 AI Runtime，无法写入 CALLBACK_*",
            "callback": build_callback_status(ai_root=None),
            "output_tail": "",
            "runtime": None,
        }

    expected_host = default_bot_callback_host()
    expected_port = default_bot_callback_port()
    if align:
        next_host = expected_host
        next_port = expected_port
    else:
        cur_host, cur_port = read_callback_settings(root)
        next_host = (host if host is not None else cur_host) or expected_host
        if port is not None:
            next_port = int(port)
        elif cur_port is not None:
            next_port = cur_port
        else:
            next_port = expected_port

    try:
        write_callback_settings(root, host=next_host, port=next_port)
    except (ValueError, RuntimeError) as err:
        return {
            "ok": False,
            "error": str(err),
            "callback": build_callback_status(ai_root=root),
            "output_tail": "",
            "runtime": ai_runtime_status(ai_root=root),
        }

    output_tail = ""
    if restart_media:
        code, out = run_ctl(root, "restart", "media", timeout_sec=180.0)
        output_tail = out[-8000:]
        if code != 0:
            return {
                "ok": False,
                "error": f"已写入 CALLBACK_*，但 restart media 退出码 {code}",
                "callback": build_callback_status(ai_root=root),
                "output_tail": output_tail,
                "runtime": ai_runtime_status(ai_root=root),
            }

    return {
        "ok": True,
        "error": None,
        "callback": build_callback_status(ai_root=root),
        "output_tail": output_tail,
        "runtime": ai_runtime_status(ai_root=root),
    }
