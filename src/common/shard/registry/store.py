"""分片注册表持久化（``data/pallas_shard/registry.json``，hub/worker 共享 data 目录）。"""

from __future__ import annotations

import json
import threading

from pydantic import BaseModel, ConfigDict, Field

from src.common.paths import plugin_data_dir
from src.common.shard.registry.config import get_shard_registry_settings

_lock = threading.Lock()
_cached: ShardRegistry | None = None

_REGISTRY_FILE = "registry.json"
_PLUGIN = "pallas_shard"


class ShardRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = Field(ge=0)
    port: int = Field(ge=1, le=65535)
    bot_ids: list[str] = Field(default_factory=list)


class ShardRegistry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: int = 1
    bots_per_shard: int = 5
    hub_port: int = 8088
    worker_base_port: int = 8090
    ws_path: str = "/onebot/v11/ws"
    ws_host: str = "127.0.0.1"
    shards: list[ShardRecord] = Field(default_factory=list)
    assignments: dict[str, int] = Field(default_factory=dict)

    def shard_for_bot(self, bot_id: str) -> int | None:
        key = str(bot_id).strip()
        if not key:
            return None
        if key in self.assignments:
            return int(self.assignments[key])
        return None

    def bots_on_shard(self, shard_id: int) -> list[str]:
        return [k for k, v in self.assignments.items() if int(v) == int(shard_id)]

    def count_on_shard(self, shard_id: int) -> int:
        return len(self.bots_on_shard(shard_id))


def _registry_path():
    root = plugin_data_dir(_PLUGIN)
    return root / _REGISTRY_FILE


def _normalize_host(host: str) -> str:
    h = (host or "").strip()
    if h in ("0.0.0.0", "::", "[::]"):
        return "127.0.0.1"
    return h or "127.0.0.1"


def worker_port_for_shard(shard_id: int, *, registry: ShardRegistry | None = None) -> int:
    reg = registry or get_shard_registry()
    for s in reg.shards:
        if s.id == shard_id:
            return s.port
    return reg.worker_base_port + int(shard_id)


def resolve_onebot_ws_url_for_bot(
    bot_id: str,
    *,
    name: str = "pallas",
    token: str = "",
) -> tuple[str, str, str]:
    """分片开启时为该 QQ 返回对应 worker 的 WS；否则返回空 url 由协议端默认逻辑补全。"""
    settings = get_shard_registry_settings()
    if not settings.enabled:
        return "", name, token
    reg = get_shard_registry()
    sid = reg.shard_for_bot(bot_id)
    if sid is None:
        sid = assign_bot_to_shard(bot_id, registry=reg)
    port = worker_port_for_shard(sid, registry=reg)
    host = _normalize_host(reg.ws_host or settings.ws_host)
    path = reg.ws_path if reg.ws_path.startswith("/") else f"/{reg.ws_path}"
    url = f"ws://{host}:{port}{path}"
    return url, name, token


def _ensure_shard_rows(reg: ShardRegistry) -> None:
    """按当前 assignments 同步 shards[].bot_ids。"""
    by_id: dict[int, ShardRecord] = {s.id: s for s in reg.shards}
    max_sid = max(reg.assignments.values(), default=-1)
    need = max(max_sid + 1, (max(len(reg.assignments), 1) + reg.bots_per_shard - 1) // reg.bots_per_shard)
    for sid in range(max(need, 1)):
        if sid not in by_id:
            by_id[sid] = ShardRecord(
                id=sid,
                port=reg.worker_base_port + sid,
                bot_ids=[],
            )
    reg.shards = sorted(by_id.values(), key=lambda x: x.id)
    for s in reg.shards:
        s.bot_ids = reg.bots_on_shard(s.id)


def get_shard_registry() -> ShardRegistry:
    from src.common.shard.data_sync import refresh_shard_data_caches_if_stale

    refresh_shard_data_caches_if_stale()
    global _cached
    with _lock:
        if _cached is not None:
            return _cached
        settings = get_shard_registry_settings()
        path = _registry_path()
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                _cached = ShardRegistry.model_validate(raw)
                return _cached
            except (json.JSONDecodeError, OSError, ValueError):
                pass
        host = _normalize_host(settings.ws_host)
        _cached = ShardRegistry(
            bots_per_shard=settings.bots_per_shard,
            hub_port=settings.hub_port,
            worker_base_port=settings.worker_base_port,
            ws_path=settings.ws_path,
            ws_host=host,
        )
        _ensure_shard_rows(_cached)
        save_shard_registry(_cached)
        return _cached


def save_shard_registry(reg: ShardRegistry) -> None:
    global _cached
    _ensure_shard_rows(reg)
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    data = reg.model_dump(mode="json")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    with _lock:
        _cached = reg
    try:
        from src.common.multi_bot.fleet import invalidate_fleet_bot_cache

        invalidate_fleet_bot_cache()
    except Exception:
        pass


def clear_shard_registry_cache() -> None:
    global _cached
    with _lock:
        _cached = None
    get_shard_registry_settings.cache_clear()


def assign_bot_to_shard(bot_id: str, *, registry: ShardRegistry | None = None) -> int:
    """将牛牛 QQ 登记到负载最轻的分片；返回 shard_id。"""
    reg = registry or get_shard_registry()
    key = str(bot_id).strip()
    if not key:
        raise ValueError("bot_id 不能为空")
    existing = reg.shard_for_bot(key)
    if existing is not None:
        return existing
    _ensure_shard_rows(reg)
    limit = reg.bots_per_shard
    candidates = sorted(reg.shards, key=lambda s: (reg.count_on_shard(s.id), s.id))
    picked = candidates[0].id if candidates else 0
    if reg.count_on_shard(picked) >= limit:
        picked = max((s.id for s in reg.shards), default=-1) + 1
        reg.shards.append(
            ShardRecord(
                id=picked,
                port=reg.worker_base_port + picked,
                bot_ids=[],
            )
        )
    reg.assignments[key] = picked
    _ensure_shard_rows(reg)
    save_shard_registry(reg)
    return picked


def rebalance_hint() -> dict[str, object]:
    reg = get_shard_registry()
    rows = [
        {"shard_id": s.id, "port": s.port, "bots": reg.bots_on_shard(s.id), "count": reg.count_on_shard(s.id)}
        for s in reg.shards
    ]
    return {
        "bots_per_shard": reg.bots_per_shard,
        "hub_port": reg.hub_port,
        "worker_base_port": reg.worker_base_port,
        "shards": rows,
        "unassigned_hint": "新账号在 create_account 时自动 assign",
    }
