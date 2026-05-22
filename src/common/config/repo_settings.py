"""仓库配置：`config/pallas.toml` + WebUI 统一 `data/pallas_config/webui.json`。

合并顺序（后者覆盖前者）：``pallas.toml`` → ``webui.json`` 的 ``env`` → 遗留 ``.env`` → ``.env.{ENVIRONMENT}``。
``repo_env_raw_value`` 以磁盘合并结果优先于 ``os.environ``；``apply_repo_settings_to_environ`` 在
``nonebot.init()`` 前把磁盘键写入环境变量，且不覆盖已存在的同名键（保留 Docker / 分片注入）。
"""

from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]


def repo_root() -> Path:
    return _REPO_ROOT


def repo_config_path() -> Path:
    return _REPO_ROOT / "config" / "pallas.toml"


def repo_webui_settings_path() -> Path:
    return _REPO_ROOT / "data" / "pallas_config" / "webui.json"


def repo_env_path() -> Path:
    """遗留 ``.env`` 路径（兼容读取，WebUI 不再写入）。"""
    return _REPO_ROOT / ".env"


def nonebot_repo_dotenv_environment() -> str:
    raw = os.environ.get("ENVIRONMENT") or os.environ.get("environment") or "prod"
    s = str(raw).strip()
    return s or "prod"


def repo_layered_dotenv_files_exist() -> bool:
    """是否存在任一磁盘配置源（供热重载判断是否回退 ``get_plugin_config``）。"""
    return repo_settings_files_exist()


def repo_settings_files_exist() -> bool:
    layered = _REPO_ROOT / f".env.{nonebot_repo_dotenv_environment()}"
    webui = repo_webui_settings_path()
    if repo_config_path().is_file():
        return True
    if webui.is_file():
        try:
            data = json.loads(webui.read_text(encoding="utf-8"))
            env = data.get("env") if isinstance(data, dict) else None
            if isinstance(env, dict) and env:
                return True
        except (json.JSONDecodeError, OSError):
            return True
    return repo_env_path().is_file() or layered.is_file()


def env_value_to_str(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if v is None:
        return ""
    return str(v)


def _load_toml_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _flatten_bootstrap(bootstrap: Any) -> dict[str, str]:
    if not isinstance(bootstrap, dict):
        return {}
    out: dict[str, str] = {}
    scalar_map = {
        "host": "HOST",
        "port": "PORT",
        "db_backend": "DB_BACKEND",
        "access_token": "ACCESS_TOKEN",
        "environment": "ENVIRONMENT",
        "log_level": "LOG_LEVEL",
    }
    for key, env_key in scalar_map.items():
        if key in bootstrap and bootstrap[key] is not None:
            out[env_key] = env_value_to_str(bootstrap[key])
    if "superusers" in bootstrap and bootstrap["superusers"] is not None:
        out["SUPERUSERS"] = env_value_to_str(bootstrap["superusers"])
    for block_name, prefix in (("mongo", "MONGO_"), ("postgres", "PG_")):
        block = bootstrap.get(block_name)
        if not isinstance(block, dict):
            continue
        for k, v in block.items():
            if v is None:
                continue
            suffix = "DB" if k == "db" else k.upper()
            out[f"{prefix}{suffix}"] = env_value_to_str(v)
    return out


def _flatten_env_section(section: Any) -> dict[str, str]:
    if not isinstance(section, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in section.items():
        if not k or v is None:
            continue
        out[str(k).upper()] = env_value_to_str(v)
    return out


def _load_pallas_toml_upper() -> dict[str, str]:
    data = _load_toml_file(repo_config_path())
    merged: dict[str, str] = {}
    merged.update(_flatten_bootstrap(data.get("bootstrap")))
    merged.update(_flatten_env_section(data.get("env")))
    return merged


def _load_webui_json_upper() -> dict[str, str]:
    path = repo_webui_settings_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    env = data.get("env")
    if not isinstance(env, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in env.items():
        if not k:
            continue
        out[str(k).upper()] = "" if v is None else str(v)
    return out


def _load_legacy_dotenv_upper() -> dict[str, str]:
    from dotenv import dotenv_values

    merged: dict[str, str] = {}
    root = repo_env_path()
    env_name = nonebot_repo_dotenv_environment()
    layered = _REPO_ROOT / f".env.{env_name}"
    if root.is_file():
        for k, v in (dotenv_values(root) or {}).items():
            if k:
                merged[str(k).upper()] = "" if v is None else str(v)
    if layered.is_file():
        for k, v in (dotenv_values(layered) or {}).items():
            if k:
                merged[str(k).upper()] = "" if v is None else str(v)
    return merged


def repo_settings_disk_revision() -> float:
    """磁盘配置源最新 mtime（hub 写入 ``webui.json`` 后 worker 可据此失效缓存）。"""
    rev = 0.0
    for path in (
        repo_config_path(),
        repo_webui_settings_path(),
        repo_env_path(),
        _REPO_ROOT / f".env.{nonebot_repo_dotenv_environment()}",
    ):
        if path.is_file():
            rev = max(rev, path.stat().st_mtime)
    return rev


def merged_repo_settings_upper() -> dict[str, str]:
    """合并磁盘配置，键名为大写；每次调用重新读盘。"""
    merged: dict[str, str] = {}
    for part in (
        _load_pallas_toml_upper,
        _load_webui_json_upper,
        _load_legacy_dotenv_upper,
    ):
        merged.update(part())
    return merged


def merged_repo_dotenv_upper() -> dict[str, str]:
    """兼容旧名。"""
    return merged_repo_settings_upper()


def repo_env_raw_value(key_upper: str) -> str | None:
    key = (key_upper or "").strip().upper()
    if not key:
        return None
    merged = merged_repo_settings_upper()
    if key in merged:
        return merged[key]
    if key in os.environ:
        return os.environ.get(key)
    return None


def apply_repo_settings_to_environ() -> None:
    """在 ``nonebot.init()`` 前调用：将磁盘配置写入 ``os.environ``（不覆盖已有键）。"""
    for k, v in merged_repo_settings_upper().items():
        if k not in os.environ:
            os.environ[k] = v


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _load_webui_json_document() -> dict[str, Any]:
    path = repo_webui_settings_path()
    if not path.is_file():
        return {"env": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"env": {}}
    if not isinstance(data, dict):
        return {"env": {}}
    env = data.get("env")
    if not isinstance(env, dict):
        data["env"] = {}
    return data


def upsert_repo_settings_items(items: dict[str, str]) -> None:
    """WebUI / 插件配置保存：写入统一 ``data/pallas_config/webui.json``。"""
    from .webui_export_toml import export_webui_inspection_toml, rebuild_webui_json_sections

    doc = _load_webui_json_document()
    env = doc.setdefault("env", {})
    if not isinstance(env, dict):
        env = {}
        doc["env"] = env
    for k, v in items.items():
        key = (k or "").strip().upper()
        if not key:
            continue
        env[key] = v
    doc["sections"] = rebuild_webui_json_sections(env)
    _atomic_write_text(
        repo_webui_settings_path(),
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
    )
    export_webui_inspection_toml(env, doc["sections"])
    for k, v in items.items():
        key = (k or "").strip().upper()
        if key:
            os.environ[key] = v


def upsert_env_dotenv_items(items: dict[str, str]) -> None:
    """兼容旧名；落盘目标为 ``webui.json``。"""
    upsert_repo_settings_items(items)
