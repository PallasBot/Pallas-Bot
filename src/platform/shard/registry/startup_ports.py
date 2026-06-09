"""分片启动前端口评估：注册表/协议端已对齐且端口空闲时可跳过写回。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path  # noqa: TC003

from src.platform.shard.registry.port_alloc import (
    all_worker_ports_free,
    allocate_worker_ports,
    worker_ports_from_registry,
)
from src.platform.shard.registry.store import get_shard_registry
from src.platform.shard.registry.sync_protocol_ports import ProtocolPortSyncResult, sync_accounts_ws_urls


@dataclass
class RegistryPortEvaluation:
    worker_ports: list[int]
    skip_registry_alloc: bool
    notes: list[str] = field(default_factory=list)


@dataclass
class ProtocolPortEvaluation:
    skip_protocol_sync: bool
    protocol_drift_count: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass
class StartupPortEvaluation:
    worker_ports: list[int]
    skip_registry_alloc: bool
    skip_protocol_sync: bool
    protocol_drift_count: int = 0
    notes: list[str] = field(default_factory=list)


def _apply_env_and_clear_cache(env_path: Path | None) -> None:
    if env_path is None or not env_path.is_file():
        return
    from src.platform.shard.registry.sync_protocol_ports import apply_env_for_shard_sync, read_dotenv

    apply_env_for_shard_sync(read_dotenv(env_path))
    from src.platform.shard.registry.config import get_shard_registry_settings

    get_shard_registry_settings.cache_clear()
    from src.platform.shard.registry.store import clear_shard_registry_cache

    clear_shard_registry_cache()


def evaluate_registry_worker_ports(
    worker_count: int,
    base_port: int,
    *,
    env_path: Path | None = None,
    skip_occupied: bool = True,
) -> RegistryPortEvaluation:
    """评估注册表 worker 端口是否需写回（不检查协议端）。"""
    from src.platform.shard.registry.config import get_shard_registry_settings

    _apply_env_and_clear_cache(env_path)
    n = max(0, int(worker_count))
    base = int(base_port)
    notes: list[str] = []

    if not get_shard_registry_settings().enabled:
        return RegistryPortEvaluation(
            worker_ports=[],
            skip_registry_alloc=True,
            notes=["分片未启用"],
        )

    planned = allocate_worker_ports(n, base, skip_occupied=skip_occupied)
    reg = get_shard_registry()
    current = worker_ports_from_registry(reg, n)

    ports_match = current == planned.ports
    ports_free = all_worker_ports_free(planned.ports) if planned.ports else True
    skip_registry = bool(ports_match and ports_free and n > 0)

    if skip_registry:
        notes.append("注册表 worker 端口已与规划一致且均空闲，跳过写回 registry")
    elif not ports_match:
        notes.append("注册表端口与规划不一致，将更新 registry")
    elif not ports_free:
        notes.append("部分 worker 端口仍被占用，将重新分配并写回 registry")

    worker_ports = current if skip_registry and current is not None else planned.ports
    return RegistryPortEvaluation(
        worker_ports=worker_ports,
        skip_registry_alloc=skip_registry,
        notes=notes,
    )


def evaluate_protocol_port_sync(
    *,
    accounts_path: Path | None = None,
    env_path: Path | None = None,
) -> ProtocolPortEvaluation:
    """对照**当前已落盘**的注册表检查协议端 ws_url（须在 registry 写回之后调用）。"""
    from src.platform.shard.registry.config import get_shard_registry_settings

    _apply_env_and_clear_cache(env_path)
    notes: list[str] = []

    if not get_shard_registry_settings().enabled:
        return ProtocolPortEvaluation(skip_protocol_sync=True, notes=["分片未启用"])

    if accounts_path is None or not accounts_path.is_file():
        return ProtocolPortEvaluation(
            skip_protocol_sync=True,
            notes=["未找到 accounts.json，跳过协议端同步"],
        )

    sync_result: ProtocolPortSyncResult = sync_accounts_ws_urls(
        accounts_path,
        env_path=env_path,
        dry_run=True,
    )
    skip_protocol = sync_result.changed_count == 0 and sync_result.onebot_drift_count == 0
    if skip_protocol:
        notes.append("协议端 ws_url 与实例 onebot 均已对齐，跳过同步")
    else:
        if sync_result.changed_count:
            notes.append(f"协议端有 {sync_result.changed_count} 个账号 ws_url 需对齐")
        if sync_result.onebot_drift_count:
            notes.append(f"协议端有 {sync_result.onebot_drift_count} 个实例 onebot WS 需对齐")
    return ProtocolPortEvaluation(
        skip_protocol_sync=skip_protocol,
        protocol_drift_count=sync_result.changed_count + sync_result.onebot_drift_count,
        notes=notes,
    )


def evaluate_shard_startup_ports(
    worker_count: int,
    base_port: int,
    *,
    accounts_path: Path | None = None,
    env_path: Path | None = None,
    skip_occupied: bool = True,
) -> StartupPortEvaluation:
    """判断可否跳过 registry 写回；协议端检查依赖当前 registry（完整启动请用 shard_startup_ports 脚本顺序）。"""
    reg_ev = evaluate_registry_worker_ports(
        worker_count,
        base_port,
        env_path=env_path,
        skip_occupied=skip_occupied,
    )
    proto_ev = evaluate_protocol_port_sync(accounts_path=accounts_path, env_path=env_path)
    return StartupPortEvaluation(
        worker_ports=reg_ev.worker_ports,
        skip_registry_alloc=reg_ev.skip_registry_alloc,
        skip_protocol_sync=proto_ev.skip_protocol_sync,
        protocol_drift_count=proto_ev.protocol_drift_count,
        notes=[*reg_ev.notes, *proto_ev.notes],
    )
