"""按分片注册表同步协议端 accounts.json 的 ws_url。"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.platform.shard.registry.store import (
    assign_bot_to_shard,
    get_shard_registry,
    resolve_onebot_ws_url_for_bot,
    save_shard_registry,
    worker_port_for_shard,
)

_account_config_manager: Any | None = None


@dataclass
class ProtocolPortSyncResult:
    changed_count: int = 0
    details: list[dict[str, object]] = field(default_factory=list)
    skipped_disabled: int = 0
    skipped_invalid: int = 0
    onebot_drift_count: int = 0
    onebot_synced_count: int = 0
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
    """端口与路径已与分片 worker 一致则视为对齐。"""
    parsed = parse_onebot_ws_url(old_url)
    if parsed is None:
        return False
    _host, port, path = parsed
    return port == int(expected_port) and path == normalize_ws_path(expected_path)


def build_ws_url(host: str, port: int, path: str) -> str:
    h = (host or "").strip() or "127.0.0.1"
    return f"ws://{h}:{int(port)}{normalize_ws_path(path)}"


def merge_ws_url_for_shard_update(old_url: str, template_url: str) -> str:
    """写回时保留账号既有 host，仅对齐端口与路径。"""
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


def resolve_account_qq(account: dict, account_id: str = "") -> str:
    return str(account.get("qq") or account.get("id") or account_id).strip()


def get_account_config_manager() -> Any:
    global _account_config_manager
    if _account_config_manager is not None:
        return _account_config_manager
    path = Path(__file__).resolve().parents[3] / "plugins" / "pallas_protocol" / "config_manager.py"
    spec = importlib.util.spec_from_file_location("_pallas_account_config_manager", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 AccountConfigManager: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _account_config_manager = mod.AccountConfigManager()
    return _account_config_manager


def read_onebot_instance_ws_url(account: dict) -> str:
    qq = resolve_account_qq(account)
    raw_dir = str(account.get("account_data_dir", "")).strip()
    if not qq or not raw_dir:
        return ""
    config_dir = Path(raw_dir) / "config"
    if not config_dir.is_dir():
        return ""
    mgr = get_account_config_manager()
    config_path = mgr._resolve_onebot_config_path(config_dir, qq)
    data = mgr.safe_read_json(config_path)
    network = data.get("network")
    if not isinstance(network, dict):
        return ""
    ws_clients = network.get("websocketClients")
    if not isinstance(ws_clients, list) or not ws_clients:
        return ""
    client = ws_clients[0]
    if not isinstance(client, dict):
        return ""
    return str(client.get("url") or "").strip()


def onebot_instance_ws_drifted(account: dict) -> bool:
    expected = str(account.get("ws_url") or "").strip()
    if not expected:
        return False
    actual = read_onebot_instance_ws_url(account)
    if not actual:
        return False
    parsed = parse_onebot_ws_url(expected)
    if parsed is None:
        return actual != expected
    _host, port, path = parsed
    return not ws_url_aligned_with_worker(actual, expected_port=port, expected_path=path)


def make_resolve_account_qq(account_id: str):
    def resolve_qq(account: dict) -> str:
        return resolve_account_qq(account, account_id)

    return resolve_qq


def sync_onebot_instances_from_accounts(
    accounts: dict,
    *,
    dry_run: bool = False,
) -> tuple[int, int]:
    """将 instances/<QQ>/config/onebot11_*.json 的 WS 与 accounts.json 对齐。"""
    mgr = get_account_config_manager()
    drift = 0
    synced = 0
    for account_id, account in accounts.items():
        if not isinstance(account, dict) or not account.get("enabled", True):
            continue
        qq = resolve_account_qq(account, account_id)
        if not qq.isdigit():
            continue
        if onebot_instance_ws_drifted(account):
            drift += 1
        if dry_run:
            continue
        mgr.sync_onebot(account, make_resolve_account_qq(account_id))
        synced += 1
    return synced, drift


def sync_accounts_ws_urls(
    accounts_path: Path,
    *,
    env_path: Path | None = None,
    backup_path: Path | None = None,
    dry_run: bool = False,
) -> ProtocolPortSyncResult:
    """将 enabled 账号 ws_url 对齐注册表分片端口；有变更且非 dry_run 时写回 accounts 与 registry。"""
    from src.platform.shard.registry.config import get_shard_registry_settings

    if env_path is not None and env_path.is_file():
        apply_env_for_shard_sync(read_dotenv(env_path))
        get_shard_registry_settings.cache_clear()
        from src.platform.shard.registry.store import clear_shard_registry_cache

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

        if reg.shard_for_bot(qq) is None:
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
    if changed and not dry_run:
        accounts_path.parent.mkdir(parents=True, exist_ok=True)
        if backup_path is not None:
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(accounts_path, backup_path)
        accounts_path.write_text(
            json.dumps(accounts, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        save_shard_registry(reg)

    onebot_synced, onebot_drift = sync_onebot_instances_from_accounts(accounts, dry_run=dry_run)
    result.onebot_synced_count = onebot_synced
    result.onebot_drift_count = onebot_drift
    return result


def format_sync_user_message(result: ProtocolPortSyncResult, *, backup_path: Path | None) -> str:
    lines: list[str] = []
    if result.changed_count:
        lines.append(f"已更新 {result.changed_count} 个协议端账号 ws_url（指向分片 worker 端口）。")
        for row in result.details[:15]:
            qq = row.get("qq")
            port = row.get("port")
            new = row.get("new")
            lines.append(f"  · QQ {qq} -> 端口 {port}  {new}")
        if len(result.details) > 15:
            lines.append(f"  · … 另有 {len(result.details) - 15} 个账号")
    if result.onebot_synced_count:
        if result.onebot_drift_count:
            lines.append(
                f"已同步 {result.onebot_synced_count} 个 NapCat/SnowLuma 实例 onebot 配置"
                f"（其中 {result.onebot_drift_count} 个与 accounts 不一致）。"
            )
        else:
            lines.append(f"已刷新 {result.onebot_synced_count} 个 NapCat/SnowLuma 实例 onebot 配置。")
    elif result.onebot_drift_count:
        lines.append(f"检测到 {result.onebot_drift_count} 个实例 onebot WS 与 accounts 不一致。")
    if backup_path is not None and result.changed_count:
        lines.append(f"备份: {backup_path}")
    if result.changed_count or result.onebot_drift_count:
        lines.append("请在协议端控制台对以上账号「重启」，使 NapCat / SnowLuma 使用新 ws_url。")
    return "\n".join(lines)


def restore_accounts_file(*, accounts_path: Path, backup_path: Path) -> None:
    if not backup_path.is_file():
        raise FileNotFoundError(f"备份不存在: {backup_path}")
    shutil.copy2(backup_path, accounts_path)
