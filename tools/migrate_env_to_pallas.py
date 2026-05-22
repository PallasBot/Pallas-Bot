#!/usr/bin/env python3
"""将仓库根 ``.env`` / ``.env.{ENVIRONMENT}`` 迁移为 ``config/pallas.toml`` + ``data/pallas_config/webui.json``。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import dotenv_values  # noqa: E402

from src.common.config.repo_settings import (  # noqa: E402
    nonebot_repo_dotenv_environment,
    repo_config_path,
    repo_env_path,
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


def _merge_legacy_env() -> dict[str, str]:
    merged: dict[str, str] = {}
    root = repo_env_path()
    layered = REPO_ROOT / f".env.{nonebot_repo_dotenv_environment()}"
    for path in (root, layered):
        if not path.is_file():
            continue
        for k, v in (dotenv_values(path) or {}).items():
            if k:
                merged[str(k).upper()] = "" if v is None else str(v)
    return merged


def _bootstrap_from_env(env: dict[str, str]) -> dict:
    boot: dict = {}
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
    mongo = {}
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
    pg = {}
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


def _toml_needs_quote(s: str) -> bool:
    if not s:
        return True
    return not _RE_IDENT.match(s)


def _toml_quote(s: str) -> str:
    if _toml_needs_quote(s):
        escaped = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return s


def _write_toml(path: Path, bootstrap: dict) -> None:
    lines = [
        "# 由 tools/migrate_env_to_pallas.py 生成；WebUI 写入见 data/pallas_config/webui.json",
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只打印将迁移的键数量")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的 pallas.toml / webui.json")
    args = parser.parse_args()

    merged = _merge_legacy_env()
    if not merged:
        print("未找到 .env 或 .env.{ENVIRONMENT}，无需迁移。", file=sys.stderr)
        return 1

    bootstrap = _bootstrap_from_env(merged)
    webui_env = {k: v for k, v in merged.items() if k not in _BOOTSTRAP_KEYS}

    cfg_path = repo_config_path()
    webui_path = repo_webui_settings_path()

    if args.dry_run:
        print(f"bootstrap 字段: {len(bootstrap)} 组, webui env 键: {len(webui_env)}")
        return 0

    if cfg_path.is_file() and not args.force:
        print(f"已存在 {cfg_path}，加 --force 覆盖或手合并。", file=sys.stderr)
        return 2
    if webui_path.is_file() and not args.force:
        print(f"已存在 {webui_path}，加 --force 覆盖或手合并。", file=sys.stderr)
        return 2

    _write_toml(cfg_path, bootstrap)
    webui_path.parent.mkdir(parents=True, exist_ok=True)
    webui_path.write_text(
        json.dumps({"env": webui_env}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"已写入 {cfg_path}")
    print(f"已写入 {webui_path}（{len(webui_env)} 项）")
    print("确认无误后可停用根目录 .env。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
