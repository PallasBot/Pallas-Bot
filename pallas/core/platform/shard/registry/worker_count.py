"""生产 worker 数量估算。"""

from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from pathlib import Path

from pallas.core.platform.shard.registry.store import (
    ShardRegistry,
    _normal_worker_need,
    is_test_shard_record,
    test_shard_ids,
)


def _normalize_ws_path(path: str) -> str:
    p = (path or "").strip() or "/"
    return p if p.startswith("/") else f"/{p}"


def _test_assigned_qqs(reg: ShardRegistry) -> set[str]:
    test_ids = test_shard_ids(reg)
    return {str(k) for k, v in reg.assignments.items() if int(v) in test_ids}


def _test_only_ws_ports(reg: ShardRegistry) -> set[int]:
    """仅由 test 分片占用的 WS 端口（不与 normal 分片共用）。"""
    test_ports = {int(s.port) for s in reg.shards if is_test_shard_record(s, reg)}
    normal_ports = {int(s.port) for s in reg.shards if not is_test_shard_record(s, reg)}
    return test_ports - normal_ports


def _is_production_account(item: dict, reg: ShardRegistry | None) -> bool:
    if not item.get("enabled", True):
        return False
    if reg is None:
        return True
    qq = str(item.get("qq") or item.get("id") or "").strip()
    if qq and qq in _test_assigned_qqs(reg):
        return False
    url = str(item.get("ws_url", "")).strip()
    if url:
        parsed = urlparse(url)
        if parsed.port is not None and int(parsed.port) in _test_only_ws_ports(reg):
            return False
    return True


def _need_from_accounts_ws(
    accounts_path: Path,
    *,
    worker_base_port: int,
    ws_path: str,
    registry: ShardRegistry | None = None,
) -> int:
    need = 0
    expected_path = _normalize_ws_path(ws_path)
    try:
        raw = json.loads(accounts_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, TypeError):
        return need
    items = raw.values() if isinstance(raw, dict) else raw
    for item in items:
        if not isinstance(item, dict) or not _is_production_account(item, registry):
            continue
        url = str(item.get("ws_url", "")).strip()
        if not url:
            continue
        parsed = urlparse(url)
        if parsed.scheme not in ("ws", "wss") or parsed.port is None:
            continue
        if _normalize_ws_path(parsed.path or "") != expected_path:
            continue
        sid = int(parsed.port) - int(worker_base_port)
        if sid >= 0:
            need = max(need, sid + 1)
    return need


def calc_production_worker_count(
    *,
    bots_per_shard: int = 7,
    worker_base_port: int | None = None,
    accounts_path: Path | None = None,
    registry: ShardRegistry | None = None,
    registry_path: Path | None = None,
) -> int:
    """按注册表、账号数与协议端 ws_url 推断应启动的生产 worker 数。"""
    bots_per = max(1, int(bots_per_shard))
    need = 1
    base = int(worker_base_port) if worker_base_port is not None else 8090
    ws_path = "/onebot/v11/ws"
    reg = registry
    if reg is None and registry_path is not None and registry_path.is_file():
        try:
            raw = json.loads(registry_path.read_text(encoding="utf-8"))
            reg = ShardRegistry.model_validate(raw)
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            reg = None

    if reg is not None:
        need = max(need, _normal_worker_need(reg))
        base = int(reg.worker_base_port)
        ws_path = reg.ws_path or ws_path

    if accounts_path is not None and accounts_path.is_file():
        try:
            raw = json.loads(accounts_path.read_text(encoding="utf-8"))
            items = raw.values() if isinstance(raw, dict) else raw
            enabled = sum(1 for v in items if isinstance(v, dict) and _is_production_account(v, reg))
            if enabled > 0:
                need = max(need, math.ceil(enabled / bots_per))
        except (json.JSONDecodeError, OSError, TypeError):
            pass
        need = max(
            need,
            _need_from_accounts_ws(
                accounts_path,
                worker_base_port=base,
                ws_path=ws_path,
                registry=reg,
            ),
        )

    return max(1, int(need))
