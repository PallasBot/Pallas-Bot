"""单进程 unified：将全部 enabled 账号 ws_url 对齐同一 HTTP/OneBot 端口。"""

from __future__ import annotations

import json
import shutil
from typing import TYPE_CHECKING

from src.platform.shard.registry.sync_protocol_ports import (
    ProtocolPortSyncResult,
    build_ws_url,
    format_sync_user_message,
    load_accounts,
    merge_ws_url_for_shard_update,
    read_dotenv,
    sync_onebot_instances_from_accounts,
    ws_url_aligned_with_worker,
)

if TYPE_CHECKING:
    from pathlib import Path


def resolve_unified_listen_port(*, env_path: Path | None = None) -> int:
    """优先 PORT / PALLAS_SHARD_HUB_PORT，其次 pallas.toml [bootstrap].port。"""
    import os

    from src.foundation.config.repo_settings import repo_config_path

    env: dict[str, str] = {}
    if env_path is not None and env_path.is_file():
        env = read_dotenv(env_path)
    for key in ("PORT", "PALLAS_SHARD_HUB_PORT"):
        raw = (os.environ.get(key) or env.get(key) or "").strip()
        if raw.isdigit():
            return int(raw)

    cfg_path = repo_config_path()
    if cfg_path.is_file():
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]
        data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
        bootstrap = data.get("bootstrap") if isinstance(data, dict) else None
        if isinstance(bootstrap, dict):
            port = bootstrap.get("port")
            if isinstance(port, int) and port > 0:
                return port
            if isinstance(port, str) and port.strip().isdigit():
                return int(port.strip())
    return 8088


def resolve_unified_ws_path(*, env_path: Path | None = None) -> str:
    import os

    env: dict[str, str] = {}
    if env_path is not None and env_path.is_file():
        env = read_dotenv(env_path)
    raw = (os.environ.get("PALLAS_SHARD_WS_PATH") or env.get("PALLAS_SHARD_WS_PATH") or "/onebot/v11/ws").strip()
    return raw if raw.startswith("/") else f"/{raw}"


def resolve_unified_ws_host(*, env_path: Path | None = None) -> str:
    import os

    env: dict[str, str] = {}
    if env_path is not None and env_path.is_file():
        env = read_dotenv(env_path)
    return (
        os.environ.get("PALLAS_SHARD_WS_HOST")
        or env.get("PALLAS_SHARD_WS_HOST")
        or os.environ.get("HOST")
        or env.get("HOST")
        or "127.0.0.1"
    ).strip() or "127.0.0.1"


def sync_accounts_ws_urls_unified(
    accounts_path: Path,
    *,
    env_path: Path | None = None,
    backup_path: Path | None = None,
    dry_run: bool = False,
    port: int | None = None,
) -> ProtocolPortSyncResult:
    """将 enabled 账号 ws_url 对齐单进程监听端口。"""
    accounts = load_accounts(accounts_path)
    listen_port = int(port) if port is not None else resolve_unified_listen_port(env_path=env_path)
    ws_path = resolve_unified_ws_path(env_path=env_path)
    template_url = build_ws_url(resolve_unified_ws_host(env_path=env_path), listen_port, ws_path)

    changed: list[dict[str, object]] = []
    skipped_disabled = 0
    skipped_invalid = 0

    for aid, acc in accounts.items():
        if not isinstance(acc, dict):
            skipped_invalid += 1
            continue
        qq = str(acc.get("qq") or acc.get("id") or aid).strip()
        if not qq.isdigit():
            skipped_invalid += 1
            continue
        if not acc.get("enabled", True):
            skipped_disabled += 1
            continue

        old_url = str(acc.get("ws_url", "")).strip()
        if old_url == template_url:
            continue
        if ws_url_aligned_with_worker(old_url, expected_port=listen_port, expected_path=ws_path):
            continue
        merged_url = merge_ws_url_for_shard_update(old_url, template_url)
        changed.append({
            "qq": qq,
            "shard_id": None,
            "port": listen_port,
            "old": old_url,
            "new": merged_url,
        })
        if not dry_run:
            acc["ws_url"] = merged_url

    result = ProtocolPortSyncResult(
        changed_count=len(changed),
        details=changed,
        skipped_disabled=skipped_disabled,
        skipped_invalid=skipped_invalid,
        dry_run=dry_run,
    )
    if changed and not dry_run:
        accounts_path.parent.mkdir(parents=True, exist_ok=True)
        if backup_path is not None:
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(accounts_path, backup_path)
        accounts_path.write_text(
            json.dumps(accounts, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    onebot_synced, onebot_drift = sync_onebot_instances_from_accounts(accounts, dry_run=dry_run)
    result.onebot_synced_count = onebot_synced
    result.onebot_drift_count = onebot_drift
    return result


def format_unified_sync_user_message(result: ProtocolPortSyncResult, *, backup_path: Path | None) -> str:
    msg = format_sync_user_message(result, backup_path=backup_path)
    return msg.replace("分片 worker 端口", "单进程 unified 端口")
