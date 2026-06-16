"""SnowLuma 配置：扁平 OneBot与 runtime.json。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlunsplit

from .docker_onebot_host import effective_docker_onebot_host
from .linux_docker import (
    is_plain_ws_url,
    rewrite_onebot_ws_url_for_container,
    ws_url_host_should_rewrite_for_docker_bridge,
)

# SnowLuma 旧版日志
_SNOWLUMA_TEMP_PASSWORD_LOG_RE = re.compile(r"临时密码[:：]\s*([0-9a-fA-F]{8,64})")
# SnowLuma initial credentials 日志格式
_SNOWLUMA_INITIAL_CREDS_LOG_RE = re.compile(
    r"initial\s+credentials:\s*user\s*=\s*admin\s+password\s*=\s*([0-9a-fA-F]{8,64})",
    re.IGNORECASE,
)
# OneBot 默认反向连接
_SNOWLUMA_DEFAULT_WS_URL = urlunsplit(("ws", "127.0.0.1:8088", "/onebot/v11/ws", "", ""))


def snowluma_onebot_path(config_dir: Path, qq: str) -> Path:
    return config_dir / f"onebot_{qq}.json"


def sync_snowluma_runtime_json(
    account: dict,
    *,
    webui_port_fallback_min: int,
    plugin_config: Any | None = None,
) -> None:
    account_data_dir = Path(str(account.get("account_data_dir", "")).strip())
    if not str(account_data_dir):
        return
    config_dir = account_data_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "runtime.json"
    data: dict[str, Any] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except Exception:
            data = {}
    if bool(account.get("snowluma_linux_docker")) and plugin_config is not None:
        port = int(getattr(plugin_config, "pallas_protocol_snowluma_docker_internal_webui_port", 5099) or 5099)
    else:
        port_raw = account.get("webui_port")
        try:
            port = int(port_raw) if port_raw is not None and str(port_raw).strip() != "" else 0
        except (TypeError, ValueError):
            port = 0
        if not (1 <= port <= 65535):
            tail = 0
            q = str(account.get("qq", "")).strip()
            if q.isdigit() and len(q) >= 3:
                tail = int(q[-3:])
            port = webui_port_fallback_min + (tail % 1000)
    data["webuiPort"] = port
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def sync_snowluma_onebot(
    cfg: Any,
    account: dict,
    resolve_qq: Any,
    *,
    plugin_config: Any | None = None,
) -> None:
    account_data_dir = Path(str(account.get("account_data_dir", "")).strip())
    if not str(account_data_dir):
        return
    qq = resolve_qq(account)
    if not qq:
        return
    config_dir = account_data_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    path = snowluma_onebot_path(config_dir, qq)
    data = cfg.safe_read_json(path)
    data.setdefault("httpServers", [{"host": "127.0.0.1", "port": 3000, "path": "/", "accessToken": ""}])
    data.setdefault("httpPostEndpoints", [])
    _ws = {"host": "127.0.0.1", "port": 3001, "path": "/", "role": "universal", "accessToken": ""}
    data.setdefault("wsServers", [_ws])
    ws_clients = data.get("wsClients")
    if not isinstance(ws_clients, list):
        ws_clients = []
    if not ws_clients:
        ws_clients.append({})
    client = ws_clients[0]
    if not isinstance(client, dict):
        client = {}
        ws_clients[0] = client
    ws_url = str(account.get("ws_url", "")).strip()
    url_out = ws_url or _SNOWLUMA_DEFAULT_WS_URL
    if bool(account.get("snowluma_linux_docker")) and plugin_config is not None:
        dh = effective_docker_onebot_host(
            str(getattr(plugin_config, "pallas_protocol_docker_onebot_host", "") or "").strip(),
            docker_network_mode="bridge",
        )
        if is_plain_ws_url(url_out) and ws_url_host_should_rewrite_for_docker_bridge(url_out):
            rw = rewrite_onebot_ws_url_for_container(url_out, dh)
            if rw:
                url_out = rw
    client["url"] = url_out
    client["name"] = str(account.get("ws_name", "pallas")).strip() or "pallas"
    client["accessToken"] = str(account.get("ws_token", "")).strip()
    client.setdefault("role", "universal")
    client.setdefault("reconnectIntervalMs", 3000)
    data["wsClients"] = ws_clients
    data.setdefault("musicSignUrl", "")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    account["onebot_config_path"] = str(path)


_RUNTIME_WEBUI_SECRET_KEYS: tuple[str, ...] = (
    "webuiPassword",
    "webUiPassword",
    "adminPassword",
    "webuiToken",
    "password",
)


def read_snowluma_runtime_webui_password(account: dict) -> str | None:
    """若 ``config/runtime.json`` 中存在常见 WebUI 凭据字段，返回其字符串值。"""
    account_data_dir = Path(str(account.get("account_data_dir", "")).strip())
    path = account_data_dir / "config" / "runtime.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    for k in _RUNTIME_WEBUI_SECRET_KEYS:
        v = raw.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def extract_snowluma_webui_temp_password_from_log_lines(lines: list[str] | None) -> str | None:
    """从 SnowLuma 进程日志解析首次启动时打印的初始口令。"""
    if not lines:
        return None
    for line in reversed(lines):
        m = _SNOWLUMA_INITIAL_CREDS_LOG_RE.search(line)
        if m:
            return m.group(1).lower()
        m = _SNOWLUMA_TEMP_PASSWORD_LOG_RE.search(line)
        if m:
            return m.group(1).lower()
    return None


def resolve_snowluma_webui_temp_password(account: dict, log_lines: list[str] | None) -> str | None:
    """仅从进程日志解析初始口令（SnowLuma 官方将口令以 scrypt 写入 ``webui.json``，无明文可读）。

    首次启动前可在协议页「一次性初始密码」写入 ``webui.json``，则无需依赖日志。
    """
    return extract_snowluma_webui_temp_password_from_log_lines(log_lines)


def read_snowluma_runtime_into_account(account: dict) -> bool:
    """从 ``config/runtime.json`` 同步 ``webui_port``。"""
    if bool(account.get("snowluma_linux_docker")):
        return False
    account_data_dir = Path(str(account.get("account_data_dir", "")).strip())
    if not account_data_dir.is_dir():
        return False
    path = account_data_dir / "config" / "runtime.json"
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    try:
        p = int(data.get("webuiPort"))
        if not (1 <= p <= 65535):
            raise ValueError
    except (TypeError, ValueError):
        return False
    try:
        cur = int(account.get("webui_port")) if account.get("webui_port") is not None else None
    except (TypeError, ValueError):
        cur = None
    if cur == p:
        return False
    account["webui_port"] = p
    return True


def get_snowluma_account_configs(cfg: Any, account: dict, resolve_qq: Any) -> dict:
    qq = resolve_qq(account)
    account_data_dir = Path(str(account.get("account_data_dir", "")).strip())
    config_dir = account_data_dir / "config"
    ob_path = snowluma_onebot_path(config_dir, qq) if qq else config_dir / "onebot_unknown.json"
    rt_path = config_dir / "runtime.json"
    return {
        "paths": {
            "onebot": str(ob_path),
            "runtime": str(rt_path),
        },
        "onebot": cfg.safe_read_json(ob_path),
        "runtime": cfg.safe_read_json(rt_path),
    }


def update_snowluma_account_configs(
    cfg: Any,
    account: dict,
    payload: dict,
    resolve_qq: Any,
) -> dict:
    qq = resolve_qq(account)
    account_data_dir = Path(str(account.get("account_data_dir", "")).strip())
    config_dir = account_data_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    if "onebot" in payload and isinstance(payload["onebot"], dict):
        ob_path = snowluma_onebot_path(config_dir, qq) if qq else config_dir / "onebot_unknown.json"
        current = cfg.safe_read_json(ob_path)
        merged = {**current, **payload["onebot"]}
        ob_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    if "runtime" in payload and isinstance(payload["runtime"], dict):
        rt_path = config_dir / "runtime.json"
        current = cfg.safe_read_json(rt_path)
        merged = {**current, **payload["runtime"]}
        rt_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        # Linux Docker：runtime.webuiPort 为容器内监听端口，账号 webui_port 为宿主机映射，勿混写。
        if not bool(account.get("snowluma_linux_docker")):
            try:
                wp = int(merged.get("webuiPort"))
                if 1 <= wp <= 65535:
                    account["webui_port"] = wp
            except (TypeError, ValueError):
                pass

    return get_snowluma_account_configs(cfg, account, resolve_qq)


__all__ = [
    "extract_snowluma_webui_temp_password_from_log_lines",
    "get_snowluma_account_configs",
    "read_snowluma_runtime_webui_password",
    "resolve_snowluma_webui_temp_password",
    "read_snowluma_runtime_into_account",
    "snowluma_onebot_path",
    "sync_snowluma_onebot",
    "sync_snowluma_runtime_json",
    "update_snowluma_account_configs",
]
