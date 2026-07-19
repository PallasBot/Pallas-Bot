"""AI Runtime 源码安装成功后的连接配置写回（仅空/缺省）。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_AI_EXTENSION_BASE_URL = "http://127.0.0.1:9099"
DEFAULT_AI_SERVER_HOST = "127.0.0.1"
DEFAULT_AI_SERVER_PORT = "9099"


def ai_extension_config_path() -> Path:
    from packages.pb_webui.data_dir import pb_webui_data_dir

    return pb_webui_data_dir() / "ai_extension.json"


def writeback_ai_extension_if_empty(*, path: Path | None = None) -> bool:
    """文件不存在或 base_url 为空时写入默认连接；已有非空 base_url 不覆盖。"""
    cfg_path = path or ai_extension_config_path()
    raw: dict[str, Any] = {}
    if cfg_path.is_file():
        try:
            loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            loaded = {}
        if isinstance(loaded, dict):
            raw = loaded
        existing = str(raw.get("base_url", "")).strip()
        if existing:
            return False

    base_url = str(raw.get("base_url", "")).strip() or DEFAULT_AI_EXTENSION_BASE_URL
    api_prefix = str(raw.get("api_prefix", "")).strip() or "/api"
    if not api_prefix.startswith("/"):
        api_prefix = "/" + api_prefix
    health_paths_raw = raw.get("health_paths", ["/health", "/api/health"])
    if isinstance(health_paths_raw, list):
        health_paths = [str(x).strip() for x in health_paths_raw if str(x).strip()]
    else:
        health_paths = ["/health", "/api/health"]
    if not health_paths:
        health_paths = ["/health", "/api/health"]
    timeout_sec = raw.get("timeout_sec", 8)
    try:
        timeout_i = max(2, min(int(timeout_sec), 30))
    except (TypeError, ValueError):
        timeout_i = 8

    clean: dict[str, Any] = {
        "base_url": base_url.rstrip("/"),
        "api_prefix": api_prefix,
        "token": str(raw.get("token", "")).strip(),
        "health_paths": health_paths,
        "timeout_sec": timeout_i,
    }
    for key in ("uvicorn_log_file", "celery_log_file", "celery_media_log_file"):
        val = str(raw.get(key, "")).strip()
        if val:
            clean[key] = val

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def writeback_ai_server_if_missing() -> bool:
    """webui.json.env 中 AI_SERVER_HOST/PORT 均缺失时写入默认值；任一已存在则不覆盖。"""
    from pallas.core.foundation.config.repo_settings import (
        _load_webui_json_upper,
        upsert_repo_settings_items,
    )

    env = _load_webui_json_upper()
    if "AI_SERVER_HOST" in env or "AI_SERVER_PORT" in env:
        return False
    upsert_repo_settings_items({
        "AI_SERVER_HOST": DEFAULT_AI_SERVER_HOST,
        "AI_SERVER_PORT": DEFAULT_AI_SERVER_PORT,
    })
    return True


def apply_ai_install_connection_writeback(*, extension_path: Path | None = None) -> dict[str, bool]:
    """bootstrap 成功后写回连接配置；返回 wrote_* 标志。"""
    wrote_ai_extension = writeback_ai_extension_if_empty(path=extension_path)
    wrote_ai_server = writeback_ai_server_if_missing()
    return {
        "wrote_ai_extension": wrote_ai_extension,
        "wrote_ai_server": wrote_ai_server,
    }
