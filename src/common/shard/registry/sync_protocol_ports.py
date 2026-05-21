"""按分片注册表同步协议端 accounts.json 的 ws_url（指向各 worker 端口）。"""

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from src.common.shard.registry.store import (
    assign_bot_to_shard,
    get_shard_registry,
    resolve_onebot_ws_url_for_bot,
    save_shard_registry,
    worker_port_for_shard,
)


@dataclass
class ProtocolPortSyncResult:
    changed_count: int = 0
    details: list[dict[str, object]] = field(default_factory=list)
    skipped_disabled: int = 0
    skipped_invalid: int = 0
    dry_run: bool = False


def read_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key and key not in out:
            out[key] = val.strip().strip('"').strip("'")
    return out


def apply_env_for_shard_sync(env: dict[str, str]) -> None:
    for key, val in env.items():
        if key and val is not None:
            os.environ.setdefault(key, val)
    os.environ["PALLAS_SHARD_ENABLED"] = "true"


def normalize_ws_path(path: str) -> str:
    p = (path or "").strip() or "/"
    return p if p.startswith("/") else f"/{p}"


def parse_onebot_ws_url(url: str) -> tuple[str, int, str] | None:
    """解析 ws://host:port/path；失败返回 None。"""
    raw = (url or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme not in ("ws", "wss"):
        return None
    host = (parsed.hostname or "").strip()
    if not host or parsed.port is None:
        return None
    return host, int(parsed.port), normalize_ws_path(parsed.path or "")


def ws_url_aligned_with_worker(old_url: str, *, expected_port: int, expected_path: str) -> bool:
    """端口与路径已与分片 worker 一致则视为对齐（主机名可不同，如 172.17.0.1 / 127.0.0.1）。"""
    parsed = parse_onebot_ws_url(old_url)
    if parsed is None:
        return False
    _host, port, path = parsed
    return port == int(expected_port) and path == normalize_ws_path(expected_path)


def build_ws_url(host: str, port: int, path: str) -> str:
    h = (host or "").strip() or "127.0.0.1"
    return f"ws://{h}:{int(port)}{normalize_ws_path(path)}"


def merge_ws_url_for_shard_update(old_url: str, template_url: str) -> str:
    """写回时保留账号既有 host（Docker 常用 172.17.0.1），仅对齐端口与路径。"""
    old = parse_onebot_ws_url(old_url)
    template = parse_onebot_ws_url(template_url)
    if template is None:
        return template_url
    host = old[0] if old is not None and old[0] else template[0]
    return build_ws_url(host, template[1], template[2])


def load_accounts(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"未找到 {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("accounts.json 须为对象")
    return raw


def sync_accounts_ws_urls(
    accounts_path: Path,
    *,
    env_path: Path | None = None,
    backup_path: Path | None = None,
    dry_run: bool = False,
) -> ProtocolPortSyncResult:
    """将 enabled 账号 ws_url 对齐注册表分片端口；有变更且非 dry_run 时写回 accounts 与 registry。"""
    from src.common.shard.registry.config import get_shard_registry_settings

    if env_path is not None and env_path.is_file():
        apply_env_for_shard_sync(read_dotenv(env_path))
        get_shard_registry_settings.cache_clear()
        from src.common.shard.registry.store import clear_shard_registry_cache

        clear_shard_registry_cache()

    settings = get_shard_registry_settings()
    if not settings.enabled:
        return ProtocolPortSyncResult(dry_run=dry_run)

    accounts = load_accounts(accounts_path)
    reg = get_shard_registry()
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

        assign_bot_to_shard(qq, registry=reg)
        template_url, _, _ = resolve_onebot_ws_url_for_bot(qq)
        if not template_url:
            continue
        template_parsed = parse_onebot_ws_url(template_url)
        if template_parsed is None:
            continue
        _reg_host, expected_port, expected_path = template_parsed
        old_url = str(acc.get("ws_url", "")).strip()
        if old_url == template_url:
            continue
        if ws_url_aligned_with_worker(
            old_url,
            expected_port=expected_port,
            expected_path=expected_path,
        ):
            continue
        merged_url = merge_ws_url_for_shard_update(old_url, template_url)
        sid = reg.shard_for_bot(qq)
        port = worker_port_for_shard(int(sid), registry=reg) if sid is not None else 0
        changed.append({
            "qq": qq,
            "shard_id": reg.shard_for_bot(qq),
            "port": port,
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
    if not changed or dry_run:
        return result

    accounts_path.parent.mkdir(parents=True, exist_ok=True)
    if backup_path is not None:
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(accounts_path, backup_path)
    accounts_path.write_text(
        json.dumps(accounts, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    save_shard_registry(reg)
    return result


def format_sync_user_message(result: ProtocolPortSyncResult, *, backup_path: Path | None) -> str:
    lines = [
        f"已更新 {result.changed_count} 个协议端账号 ws_url（指向分片 worker 端口）。",
    ]
    for row in result.details[:15]:
        qq = row.get("qq")
        port = row.get("port")
        new = row.get("new")
        lines.append(f"  · QQ {qq} -> 端口 {port}  {new}")
    if len(result.details) > 15:
        lines.append(f"  · … 另有 {len(result.details) - 15} 个账号")
    if backup_path is not None:
        lines.append(f"备份: {backup_path}")
    lines.append("请在协议端控制台对以上账号「重启」，使 NapCat / SnowLuma 使用新 ws_url。")
    return "\n".join(lines)


def restore_accounts_file(*, accounts_path: Path, backup_path: Path) -> None:
    if not backup_path.is_file():
        raise FileNotFoundError(f"备份不存在: {backup_path}")
    shutil.copy2(backup_path, accounts_path)
