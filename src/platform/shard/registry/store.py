"""分片注册表持久化。"""

from __future__ import annotations

import json
import threading

from pydantic import BaseModel, ConfigDict, Field

from src.foundation.paths import plugin_data_dir
from src.platform.shard.registry.config import get_shard_registry_settings

_lock = threading.Lock()
_cached: ShardRegistry | None = None

_REGISTRY_FILE = "registry.json"
_PLUGIN = "pallas_shard"
TEST_SHARD_ROLE = "test"
NORMAL_SHARD_ROLE = "normal"


class TestShardConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    shard_id: int = Field(default=99, ge=0, le=255)
    port: int = Field(default=0, ge=0, le=65535)
    auto_assign: bool = False


class ShardRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = Field(ge=0)
    port: int = Field(ge=1, le=65535)
    bot_ids: list[str] = Field(default_factory=list)
    role: str = NORMAL_SHARD_ROLE


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
    test: TestShardConfig | None = None

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


def apply_registry_settings_from_env(reg: ShardRegistry) -> bool:
    """用 .env / 进程环境覆盖注册表顶层运行参数。"""
    settings = get_shard_registry_settings()
    changed = False
    pairs = (
        ("bots_per_shard", settings.bots_per_shard),
        ("hub_port", settings.hub_port),
        ("worker_base_port", settings.worker_base_port),
        ("ws_path", settings.ws_path),
    )
    for key, val in pairs:
        if getattr(reg, key) != val:
            setattr(reg, key, val)
            changed = True
    host = _normalize_host(settings.ws_host)
    if reg.ws_host != host:
        reg.ws_host = host
        changed = True
    return changed


def next_auto_assign_shard_id(reg: ShardRegistry) -> int:
    """下一个可用于自动负载的生产分片 id。"""
    test_sid = get_test_shard_id(reg)
    normal_ids = [int(s.id) for s in reg.shards if not is_test_shard_record(s, reg)]
    picked = max(normal_ids, default=-1) + 1
    while picked == test_sid:
        picked += 1
    return picked


def _normal_worker_need(reg: ShardRegistry) -> int:
    test_sid = get_test_shard_id(reg)
    normal_assigns = [int(v) for v in reg.assignments.values() if int(v) != test_sid]
    if not normal_assigns:
        return 1
    max_sid = max(normal_assigns)
    normal_count = len(normal_assigns)
    return max(
        max_sid + 1,
        (max(normal_count, 1) + reg.bots_per_shard - 1) // reg.bots_per_shard,
    )


def get_test_config(reg: ShardRegistry) -> TestShardConfig:
    settings = get_shard_registry_settings()
    if reg.test is not None:
        return reg.test
    return TestShardConfig(
        enabled=False,
        shard_id=settings.test_shard_id,
        port=settings.test_port,
        auto_assign=False,
    )


def get_test_shard_id(reg: ShardRegistry | None = None) -> int:
    reg = reg or get_shard_registry()
    return int(get_test_config(reg).shard_id)


def is_test_shard_id(shard_id: int, reg: ShardRegistry | None = None) -> bool:
    reg = reg or get_shard_registry()
    return int(shard_id) == get_test_shard_id(reg)


def is_test_shard_record(shard: ShardRecord, reg: ShardRegistry | None = None) -> bool:
    reg = reg or get_shard_registry()
    if (shard.role or NORMAL_SHARD_ROLE).strip().lower() == TEST_SHARD_ROLE:
        return True
    return is_test_shard_id(shard.id, reg)


def resolve_test_port(reg: ShardRegistry) -> int:
    tc = get_test_config(reg)
    if int(tc.port) > 0:
        return int(tc.port)
    sid = get_test_shard_id(reg)
    normal_ports = [int(s.port) for s in reg.shards if int(s.id) != sid]
    base = int(reg.worker_base_port)
    peak = max(normal_ports) if normal_ports else base - 1
    return max(peak, base) + 1


def ensure_test_shard_row(reg: ShardRegistry) -> None:
    """确保 test 分片在 shards 中有对应行。"""
    tc = get_test_config(reg)
    if not tc.enabled and reg.count_on_shard(tc.shard_id) == 0:
        return
    sid = int(tc.shard_id)
    port = resolve_test_port(reg)
    tc.port = port
    reg.test = tc
    by_id = {int(s.id): s for s in reg.shards}
    row = by_id.get(sid)
    if row is None:
        by_id[sid] = ShardRecord(id=sid, port=port, role=TEST_SHARD_ROLE, bot_ids=[])
    else:
        row.port = port
        row.role = TEST_SHARD_ROLE
    reg.shards = sorted(by_id.values(), key=lambda x: x.id)
    for s in reg.shards:
        if int(s.id) == sid:
            s.bot_ids = reg.bots_on_shard(sid)


def init_test_shard(
    *,
    registry: ShardRegistry | None = None,
    port: int = 0,
    shard_id: int | None = None,
) -> TestShardConfig:
    """启用测试分片并写入注册表。"""
    reg = registry or get_shard_registry()
    settings = get_shard_registry_settings()
    tc = get_test_config(reg)
    tc.enabled = True
    tc.auto_assign = False
    if shard_id is not None:
        tc.shard_id = int(shard_id)
    elif tc.shard_id <= 0:
        tc.shard_id = settings.test_shard_id
    if port > 0:
        tc.port = int(port)
    elif settings.test_port > 0:
        tc.port = int(settings.test_port)
    reg.test = tc
    ensure_test_shard_row(reg)
    _ensure_shard_rows(reg)
    save_shard_registry(reg)
    return get_test_config(reg)


def assign_bot_to_test_shard(bot_id: str, *, registry: ShardRegistry | None = None) -> int:
    """手动将牛牛登记到测试分片。"""
    reg = registry or get_shard_registry()
    tc = get_test_config(reg)
    if not tc.enabled:
        raise ValueError("测试分片未启用，请先执行: ./scripts/run_sharded_bot.sh test init")
    key = str(bot_id).strip()
    if not key:
        raise ValueError("bot_id 不能为空")
    ensure_test_shard_row(reg)
    sid = get_test_shard_id(reg)
    reg.assignments[key] = sid
    _ensure_shard_rows(reg)
    save_shard_registry(reg)
    return sid


def remove_bot_from_test_shard(bot_id: str, *, registry: ShardRegistry | None = None) -> bool:
    reg = registry or get_shard_registry()
    key = str(bot_id).strip()
    if not key or key not in reg.assignments:
        return False
    if not is_test_shard_id(reg.assignments[key], reg):
        raise ValueError(f"账号 {key} 不在测试分片（当前 shard {reg.assignments[key]}）")
    del reg.assignments[key]
    _ensure_shard_rows(reg)
    save_shard_registry(reg)
    return True


def list_test_shard_bots(*, registry: ShardRegistry | None = None) -> list[str]:
    reg = registry or get_shard_registry()
    return reg.bots_on_shard(get_test_shard_id(reg))


def worker_port_for_shard(shard_id: int, *, registry: ShardRegistry | None = None) -> int:
    reg = registry or get_shard_registry()
    for s in reg.shards:
        if s.id == shard_id:
            return s.port
    if is_test_shard_id(shard_id, reg):
        return resolve_test_port(reg)
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


def _auto_assign_shard_candidates(reg: ShardRegistry) -> list[ShardRecord]:
    return [s for s in reg.shards if not is_test_shard_record(s, reg)]


def _ensure_shard_rows(reg: ShardRegistry) -> None:
    """按 assignments 同步 shards[].bot_ids，并裁剪多余空分片。"""
    test_sid = get_test_shard_id(reg)
    by_id: dict[int, ShardRecord] = {int(s.id): s for s in reg.shards}
    need = _normal_worker_need(reg)
    kept: dict[int, ShardRecord] = {}
    for sid in range(max(need, 1)):
        if sid == test_sid:
            continue
        row = by_id.get(sid)
        kept[sid] = row or ShardRecord(
            id=sid,
            port=reg.worker_base_port + sid,
            bot_ids=[],
            role=NORMAL_SHARD_ROLE,
        )
        kept[sid].role = NORMAL_SHARD_ROLE
        kept[sid].port = reg.worker_base_port + sid
    for sid, row in by_id.items():
        if sid in kept or sid == test_sid or is_test_shard_record(row, reg):
            continue
        if reg.count_on_shard(sid) > 0:
            row.role = NORMAL_SHARD_ROLE
            kept[sid] = row
    reg.shards = sorted(kept.values(), key=lambda x: x.id)
    for s in reg.shards:
        s.bot_ids = reg.bots_on_shard(s.id)
    ensure_test_shard_row(reg)


def get_shard_registry() -> ShardRegistry:
    from src.platform.shard.data_sync import refresh_shard_data_caches_if_stale

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
                apply_registry_settings_from_env(_cached)
                _ensure_shard_rows(_cached)
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
        from src.platform.multi_bot.fleet import invalidate_fleet_bot_cache

        invalidate_fleet_bot_cache()
    except Exception:
        pass


def clear_shard_registry_cache() -> None:
    global _cached
    with _lock:
        _cached = None
    get_shard_registry_settings.cache_clear()


def assign_bot_to_shard(bot_id: str, *, registry: ShardRegistry | None = None) -> int:
    """将牛牛 QQ 登记到负载最轻的生产分片；返回 shard_id。"""
    reg = registry or get_shard_registry()
    key = str(bot_id).strip()
    if not key:
        raise ValueError("bot_id 不能为空")
    existing = reg.shard_for_bot(key)
    if existing is not None:
        return existing
    _ensure_shard_rows(reg)
    limit = reg.bots_per_shard
    candidates = sorted(
        _auto_assign_shard_candidates(reg),
        key=lambda s: (reg.count_on_shard(s.id), s.id),
    )
    if not candidates:
        picked = 0
        reg.shards.append(
            ShardRecord(
                id=picked,
                port=reg.worker_base_port + picked,
                bot_ids=[],
                role=NORMAL_SHARD_ROLE,
            )
        )
    else:
        picked = candidates[0].id
    if reg.count_on_shard(picked) >= limit:
        picked = next_auto_assign_shard_id(reg)
        reg.shards.append(
            ShardRecord(
                id=picked,
                port=reg.worker_base_port + picked,
                bot_ids=[],
                role=NORMAL_SHARD_ROLE,
            )
        )
    reg.assignments[key] = picked
    _ensure_shard_rows(reg)
    save_shard_registry(reg)
    try:
        from src.platform.shard.worker_scale import schedule_worker_scale_restart

        schedule_worker_scale_restart(reason=f"assign {key} -> shard {picked}")
    except Exception as err:
        import logging

        logging.getLogger(__name__).debug("worker scale schedule skipped: %s", err)
    return picked


def rebalance_hint() -> dict[str, object]:
    reg = get_shard_registry()
    tc = get_test_config(reg)
    test_sid = get_test_shard_id(reg)
    rows = [
        {
            "shard_id": s.id,
            "port": s.port,
            "role": s.role,
            "bots": reg.bots_on_shard(s.id),
            "count": reg.count_on_shard(s.id),
        }
        for s in reg.shards
        if not is_test_shard_record(s, reg)
    ]
    return {
        "bots_per_shard": reg.bots_per_shard,
        "hub_port": reg.hub_port,
        "worker_base_port": reg.worker_base_port,
        "shards": rows,
        "test": {
            "enabled": tc.enabled,
            "shard_id": test_sid,
            "port": resolve_test_port(reg) if tc.enabled or reg.count_on_shard(test_sid) else tc.port,
            "bots": reg.bots_on_shard(test_sid),
            "count": reg.count_on_shard(test_sid),
            "auto_assign": tc.auto_assign,
        },
        "unassigned_hint": "新账号在 create_account 时自动 assign（不进入 test 分片）",
        "test_hint": "测试账号请用 test add 手动迁入 test 分片",
    }
