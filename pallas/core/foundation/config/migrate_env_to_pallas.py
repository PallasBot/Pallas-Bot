"""将遗留 ``.env`` 迁移为 ``config/pallas.toml`` + ``data/pallas_config/webui.json``。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from pallas.core.foundation.config.repo_settings import (
    nonebot_repo_dotenv_environment,
    repo_config_path,
    repo_env_path,
    repo_root,
    repo_webui_settings_path,
)

_RE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")

_BOOTSTRAP_KEYS = frozenset({
    "HOST",
    "PORT",
    "SUPERUSERS",
    "DB_BACKEND",
    "ACCESS_TOKEN",
    "ENVIRONMENT",
    "LOG_LEVEL",
    "MONGO_HOST",
    "MONGO_PORT",
    "MONGO_USER",
    "MONGO_PASSWORD",
    "MONGO_DB",
    "MONGO_AUTH_SOURCE",
    "PG_HOST",
    "PG_PORT",
    "PG_USER",
    "PG_PASSWORD",
    "PG_DB",
})


class EnvToPallasMigrationError(Exception):
    """配置迁移失败。"""

    def __init__(self, detail: str, *, status_code: int = 400) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass(frozen=True)
class EnvToPallasMigrationResult:
    config_path: str
    webui_path: str
    bootstrap_field_groups: int
    webui_env_key_count: int
    legacy_env_key_count: int
    legacy_env_files: tuple[str, ...]
    overwritten: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "config_path": self.config_path,
            "webui_path": self.webui_path,
            "bootstrap_field_groups": self.bootstrap_field_groups,
            "webui_env_key_count": self.webui_env_key_count,
            "legacy_env_key_count": self.legacy_env_key_count,
            "legacy_env_files": list(self.legacy_env_files),
            "overwritten": self.overwritten,
            "message": (
                f"已写入 {Path(self.config_path).name} 与 {self.webui_path} "
                f"（{self.webui_env_key_count} 项插件/通用配置）。"
                "可保留 .env 专放 nb/pip 插件项；与 webui.json 避免同名键重复。"
                "pip 插件须在 pyproject.toml 的 [tool.nonebot.plugins] 注册后才会加载。"
            ),
        }


def legacy_env_file_paths() -> list[Path]:
    paths: list[Path] = []
    root = repo_env_path()
    if root.is_file():
        paths.append(root)
    layered = repo_root() / f".env.{nonebot_repo_dotenv_environment()}"
    if layered.is_file():
        paths.append(layered)
    return paths


def merge_legacy_env() -> dict[str, str]:
    merged: dict[str, str] = {}
    for path in legacy_env_file_paths():
        for k, v in (dotenv_values(path) or {}).items():
            if k:
                merged[str(k).upper()] = "" if v is None else str(v)
    return merged


def bootstrap_from_env(env: dict[str, str]) -> dict[str, Any]:
    boot: dict[str, Any] = {}
    if "HOST" in env:
        boot["host"] = env["HOST"]
    if "PORT" in env:
        boot["port"] = int(env["PORT"]) if str(env["PORT"]).isdigit() else env["PORT"]
    if "SUPERUSERS" in env:
        raw = env["SUPERUSERS"].strip()
        if raw.startswith("["):
            boot["superusers"] = json.loads(raw)
        else:
            boot["superusers"] = [x.strip() for x in raw.split(",") if x.strip()]
    if "DB_BACKEND" in env:
        boot["db_backend"] = env["DB_BACKEND"]
    if "ACCESS_TOKEN" in env and env["ACCESS_TOKEN"]:
        boot["access_token"] = env["ACCESS_TOKEN"]
    mongo: dict[str, Any] = {}
    for ek, tk in (
        ("MONGO_HOST", "host"),
        ("MONGO_PORT", "port"),
        ("MONGO_USER", "user"),
        ("MONGO_PASSWORD", "password"),
        ("MONGO_DB", "db"),
        ("MONGO_AUTH_SOURCE", "auth_source"),
    ):
        if ek in env and env[ek]:
            val = env[ek]
            mongo[tk] = int(val) if ek == "MONGO_PORT" and str(val).isdigit() else val
    if mongo:
        boot["mongo"] = mongo
    pg: dict[str, Any] = {}
    for ek, tk in (
        ("PG_HOST", "host"),
        ("PG_PORT", "port"),
        ("PG_USER", "user"),
        ("PG_PASSWORD", "password"),
        ("PG_DB", "db"),
    ):
        if ek in env and env[ek]:
            val = env[ek]
            pg[tk] = int(val) if ek == "PG_PORT" and str(val).isdigit() else val
    if pg:
        boot["postgres"] = pg
    return boot


def inspect_env_to_pallas_migration() -> dict[str, Any]:
    legacy_files = legacy_env_file_paths()
    merged = merge_legacy_env()
    cfg_path = repo_config_path()
    webui_path = repo_webui_settings_path()
    pallas_exists = cfg_path.is_file()
    webui_exists = webui_path.is_file()
    legacy_count = len(merged)
    rel_legacy = [str(p.relative_to(repo_root())) for p in legacy_files]

    show = legacy_count > 0
    needs_force = show and pallas_exists and webui_exists
    can_migrate = show and not (pallas_exists and webui_exists)
    suggest_cleanup = show and pallas_exists and webui_exists

    return {
        "show": show,
        "legacy_env_files": rel_legacy,
        "legacy_env_key_count": legacy_count,
        "pallas_toml_exists": pallas_exists,
        "webui_json_exists": webui_exists,
        "can_migrate": can_migrate,
        "needs_force": needs_force,
        "suggest_cleanup_legacy_env": suggest_cleanup,
    }


def _toml_quote(s: str) -> str:
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def write_pallas_toml(path: Path, bootstrap: dict[str, Any]) -> None:
    lines = [
        "# 由 migrate_env_to_pallas 生成；WebUI 写入见 data/pallas_config/webui.json",
        "",
        "[bootstrap]",
    ]
    if "host" in bootstrap:
        lines.append(f"host = {_toml_quote(str(bootstrap['host']))}")
    if "port" in bootstrap:
        lines.append(f"port = {bootstrap['port']}")
    if "superusers" in bootstrap:
        su = bootstrap["superusers"]
        if isinstance(su, list):
            inner = ", ".join(_toml_quote(str(x)) for x in su)
            lines.append(f"superusers = [{inner}]")
    if "db_backend" in bootstrap:
        lines.append(f"db_backend = {_toml_quote(str(bootstrap['db_backend']))}")
    if bootstrap.get("access_token"):
        lines.append(f"access_token = {_toml_quote(str(bootstrap['access_token']))}")
    for block_name in ("mongo", "postgres"):
        block = bootstrap.get(block_name)
        if not isinstance(block, dict):
            continue
        lines.extend(("", f"[bootstrap.{block_name}]"))
        for k, v in block.items():
            if v is None or v == "":
                continue
            key = k if _RE_IDENT.match(k) else f'"{k}"'
            if isinstance(v, bool):
                lines.append(f"{key} = {'true' if v else 'false'}")
            elif isinstance(v, int):
                lines.append(f"{key} = {v}")
            else:
                lines.append(f"{key} = {_toml_quote(str(v))}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def apply_env_to_pallas_migration(*, force: bool = False) -> EnvToPallasMigrationResult:
    merged = merge_legacy_env()
    if not merged:
        raise EnvToPallasMigrationError(
            "未找到根目录 .env 或 .env.{ENVIRONMENT}，无需迁移。",
            status_code=400,
        )

    bootstrap = bootstrap_from_env(merged)
    webui_env = {k: v for k, v in merged.items() if k not in _BOOTSTRAP_KEYS}

    cfg_path = repo_config_path()
    webui_path = repo_webui_settings_path()
    pallas_exists = cfg_path.is_file()
    webui_exists = webui_path.is_file()

    if (pallas_exists or webui_exists) and not force:
        existing: list[str] = []
        if pallas_exists:
            existing.append(str(cfg_path.relative_to(repo_root())))
        if webui_exists:
            existing.append(str(webui_path.relative_to(repo_root())))
        joined = "、".join(existing)
        raise EnvToPallasMigrationError(
            f"已存在 {joined}。若确认覆盖请先备份，再在控制台勾选强制迁移或使用 --force。",
            status_code=409,
        )

    write_pallas_toml(cfg_path, bootstrap)
    webui_path.parent.mkdir(parents=True, exist_ok=True)
    webui_path.write_text(
        json.dumps({"env": webui_env}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    legacy_files = tuple(str(p.relative_to(repo_root())) for p in legacy_env_file_paths())
    return EnvToPallasMigrationResult(
        config_path=str(cfg_path.relative_to(repo_root())),
        webui_path=str(webui_path.relative_to(repo_root())),
        bootstrap_field_groups=len(bootstrap),
        webui_env_key_count=len(webui_env),
        legacy_env_key_count=len(merged),
        legacy_env_files=legacy_files,
        overwritten=force and (pallas_exists or webui_exists),
    )
