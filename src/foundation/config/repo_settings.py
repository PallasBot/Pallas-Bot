"""仓库配置：`config/pallas.toml` + WebUI 统一 `data/pallas_config/webui.json`。

合并顺序：``pallas.toml`` → 遗留 ``.env`` → ``.env.{ENVIRONMENT}`` →
``webui.json`` 的 ``env``。
``repo_env_raw_value`` 以磁盘合并结果优先于 ``os.environ``；``apply_repo_settings_to_environ`` 在
``nonebot.init()`` 前把磁盘键写入环境变量，且不覆盖已存在的同名键。
"""

from __future__ import annotations

import json
import logging
import os
import tomllib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from src.foundation.paths import PROJECT_ROOT as _REPO_ROOT

_log = logging.getLogger(__name__)


def repo_root() -> Path:
    return _REPO_ROOT


def repo_config_path() -> Path:
    return _REPO_ROOT / "config" / "pallas.toml"


def read_bootstrap_extra_plugin_dirs() -> list[str]:
    """``[bootstrap].extra_plugin_dirs``：站点自有插件目录。"""
    data = _load_toml_file(repo_config_path())
    raw: object | None = None
    bootstrap = data.get("bootstrap")
    if isinstance(bootstrap, dict):
        raw = bootstrap.get("extra_plugin_dirs")
    if not isinstance(raw, list):
        top = data.get("extra_plugin_dirs")
        if isinstance(top, list):
            _log.warning(
                "config/pallas.toml: extra_plugin_dirs 应写在 [bootstrap] 段内，"
                "当前写在文件顶层仍会被读取，请迁入 [bootstrap] 以免后续版本不再兼容"
            )
            raw = top
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        s = str(item).strip().replace("\\", "/").rstrip("/").removeprefix("./")
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def repo_webui_settings_path() -> Path:
    return _REPO_ROOT / "data" / "pallas_config" / "webui.json"


def repo_env_path() -> Path:
    """遗留 ``.env`` 路径。"""
    return _REPO_ROOT / ".env"


def nonebot_repo_dotenv_environment() -> str:
    raw = os.environ.get("ENVIRONMENT") or os.environ.get("environment") or "prod"
    s = str(raw).strip()
    return s or "prod"


def repo_layered_dotenv_files_exist() -> bool:
    """是否存在任一磁盘配置源。"""
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


def _flatten_corpus(section: Any) -> dict[str, str]:
    if not isinstance(section, dict):
        return {}
    key_map = {
        "merge_order": "PALLAS_CORPUS_MERGE_ORDER",
        "merge_strategy": "PALLAS_CORPUS_MERGE_STRATEGY",
        "fed_enabled": "PALLAS_CORPUS_FED_ENABLED",
        "community_enabled": "PALLAS_CORPUS_COMMUNITY_ENABLED",
        "auto_enroll": "PALLAS_CORPUS_AUTO_ENROLL",
        "fed_contribute": "PALLAS_CORPUS_FED_CONTRIBUTE",
        "community_contribute": "PALLAS_CORPUS_COMMUNITY_CONTRIBUTE",
        "on_remote_failure": "PALLAS_CORPUS_ON_REMOTE_FAILURE",
    }
    out: dict[str, str] = {}
    for k, env_key in key_map.items():
        if k in section and section[k] is not None:
            out[env_key] = env_value_to_str(section[k])
    community = section.get("community")
    if isinstance(community, dict):
        if community.get("api_base") is not None:
            out["PALLAS_CORPUS_COMMUNITY_API_BASE"] = env_value_to_str(community["api_base"])
        if community.get("token") is not None:
            out["PALLAS_CORPUS_TOKEN"] = env_value_to_str(community["token"])
    return out


def _flatten_control_plane(section: Any) -> dict[str, str]:
    if not isinstance(section, dict):
        return {}
    key_map = {
        "enabled": "PALLAS_CONTROL_PLANE_ENABLED",
        "bootstrap_url": "PALLAS_CONTROL_PLANE_BOOTSTRAP_URL",
        "instance_secret": "PALLAS_INSTANCE_SECRET",
        "federate_id": "PALLAS_FEDERATE_ID",
        "ingress_enabled": "PALLAS_FEDERATE_INGRESS_ENABLED",
        "redis_prefix": "PALLAS_FEDERATE_REDIS_PREFIX",
    }
    out: dict[str, str] = {}
    for k, env_key in key_map.items():
        if k in section and section[k] is not None:
            out[env_key] = env_value_to_str(section[k])
    coord = section.get("coord")
    if isinstance(coord, dict):
        if coord.get("redis_url") is not None:
            out["PALLAS_FEDERATE_COORD_REDIS_URL"] = env_value_to_str(coord["redis_url"])
        if coord.get("redis_prefix") is not None:
            out["PALLAS_FEDERATE_REDIS_PREFIX"] = env_value_to_str(coord["redis_prefix"])
        if coord.get("claim_ttl_sec") is not None:
            out["PALLAS_FEDERATE_CLAIM_TTL_SEC"] = env_value_to_str(coord["claim_ttl_sec"])
    return out


def _flatten_community_stats(section: Any) -> dict[str, str]:
    if not isinstance(section, dict):
        return {}
    key_map = {
        "enabled": "PALLAS_COMMUNITY_STATS_ENABLED",
        "endpoint": "PALLAS_COMMUNITY_STATS_ENDPOINT",
        "token": "PALLAS_COMMUNITY_STATS_TOKEN",
        "interval_sec": "PALLAS_COMMUNITY_STATS_INTERVAL_SEC",
        "roster_public_qq": "PALLAS_COMMUNITY_STATS_ROSTER_PUBLIC_QQ",
        "roster_public_profile": "PALLAS_COMMUNITY_STATS_ROSTER_PUBLIC_PROFILE",
    }
    out: dict[str, str] = {}
    for k, env_key in key_map.items():
        if k in section and section[k] is not None:
            out[env_key] = env_value_to_str(section[k])
    return out


def _load_pallas_toml_upper() -> dict[str, str]:
    data = _load_toml_file(repo_config_path())
    merged: dict[str, str] = {}
    merged.update(_flatten_bootstrap(data.get("bootstrap")))
    merged.update(_flatten_community_stats(data.get("community_stats")))
    merged.update(_flatten_control_plane(data.get("control_plane")))
    merged.update(_flatten_corpus(data.get("corpus")))
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


def repo_settings_disk_revision() -> tuple[tuple[int, int], ...]:
    """各磁盘配置源的 (mtime_ns, size)；hub 写入 webui.json 后 worker 可据此失效缓存。"""
    parts: list[tuple[int, int]] = []
    for path in (
        repo_config_path(),
        repo_webui_settings_path(),
        repo_env_path(),
        _REPO_ROOT / f".env.{nonebot_repo_dotenv_environment()}",
    ):
        if path.is_file():
            st = path.stat()
            parts.append((st.st_mtime_ns, st.st_size))
    return tuple(parts)


_merged_settings_cache: dict[str, str] | None = None
_merged_settings_cache_rev: tuple[tuple[int, int], ...] | None = None


def clear_merged_repo_settings_cache() -> None:
    global _merged_settings_cache, _merged_settings_cache_rev
    _merged_settings_cache = None
    _merged_settings_cache_rev = None


def merged_repo_settings_upper() -> dict[str, str]:
    """合并磁盘配置，键名为大写；同进程内按磁盘 revision 缓存，避免热路径反复读盘。"""
    global _merged_settings_cache, _merged_settings_cache_rev
    rev = repo_settings_disk_revision()
    if _merged_settings_cache is not None and _merged_settings_cache_rev == rev:
        return _merged_settings_cache
    merged: dict[str, str] = {}
    for part in (
        _load_pallas_toml_upper,
        _load_legacy_dotenv_upper,
        _load_webui_json_upper,
    ):
        merged.update(part())
    _merged_settings_cache = merged
    _merged_settings_cache_rev = rev
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
    """在 ``nonebot.init()`` 前调用：将磁盘配置写入 ``os.environ``。"""
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
    clear_merged_repo_settings_cache()
    for k, v in items.items():
        key = (k or "").strip().upper()
        if key:
            os.environ[key] = v


def remove_repo_settings_keys(keys: list[str]) -> None:
    """从 ``webui.json`` 的 ``env`` 删除键。"""
    from .webui_export_toml import export_webui_inspection_toml, rebuild_webui_json_sections

    doc = _load_webui_json_document()
    env = doc.setdefault("env", {})
    if not isinstance(env, dict):
        return
    removed = False
    for raw in keys:
        key = (raw or "").strip().upper()
        if key in env:
            env.pop(key, None)
            removed = True
        os.environ.pop(key, None)
    if not removed:
        return
    doc["sections"] = rebuild_webui_json_sections(env)
    _atomic_write_text(
        repo_webui_settings_path(),
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
    )
    export_webui_inspection_toml(env, doc["sections"])
    clear_merged_repo_settings_cache()


def upsert_env_dotenv_items(items: dict[str, str]) -> None:
    """兼容旧名；落盘目标为 ``webui.json``。"""
    upsert_repo_settings_items(items)
