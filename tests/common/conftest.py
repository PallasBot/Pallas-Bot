"""
PostgreSQL 集成测试共用 fixture。

需要本地 PG 实例：通过环境变量 ``PG_TEST_DSN`` 注入 SQLAlchemy asyncpg DSN，
例如 ``postgresql+asyncpg://user:pw@/db?host=/run/postgresql``。未设置时依赖
这些 fixture 的测试将被自动 skip。
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

import pytest

PG_TEST_DSN = os.getenv("PG_TEST_DSN")
_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _reset_common_runtime_state():
    """隔离 common 测试使用的进程级缓存和动态导入模块。"""
    original_env = os.environ.copy()
    from nonebot import matcher as nb_matcher

    from pallas.core.platform.multi_bot import dedup
    from pallas.core.platform.shard import ingress_metrics
    from pallas.core.platform.shard.coord import repeater_buffer, repeater_reply_buffer
    from pallas.core.platform.shard.registry import config as shard_config
    from pallas.core.platform.shard.registry import store as shard_store

    original_matchers = {priority: list(items) for priority, items in nb_matcher.matchers.items()}
    repeater_buffer._seen_event_ids.clear()
    repeater_buffer._seen_set.clear()
    repeater_reply_buffer._seen_event_ids.clear()
    repeater_reply_buffer._seen_set.clear()
    nb_matcher.matchers.clear()
    dedup._cross_bot_claim_owners.clear()
    dedup._shard_ingress_file_locks.clear()
    dedup._group_message_once_keys.clear()
    dedup._group_message_once_order.clear()
    dedup._group_event_sigs.clear()
    dedup._group_event_sig_set.clear()
    ingress_metrics.clear_ingress_metrics_for_tests()
    shard_store.clear_shard_registry_cache()
    shard_config.get_shard_registry_settings.cache_clear()
    yield
    for key in set(os.environ) - set(original_env):
        del os.environ[key]
    os.environ.update(original_env)
    repeater_buffer._seen_event_ids.clear()
    repeater_buffer._seen_set.clear()
    repeater_reply_buffer._seen_event_ids.clear()
    repeater_reply_buffer._seen_set.clear()
    nb_matcher.matchers.clear()
    nb_matcher.matchers.update({priority: list(items) for priority, items in original_matchers.items()})
    dedup._cross_bot_claim_owners.clear()
    dedup._shard_ingress_file_locks.clear()
    dedup._group_message_once_keys.clear()
    dedup._group_message_once_order.clear()
    dedup._group_event_sigs.clear()
    dedup._group_event_sig_set.clear()
    ingress_metrics.clear_ingress_metrics_for_tests()
    shard_store.clear_shard_registry_cache()
    shard_config.get_shard_registry_settings.cache_clear()


@pytest.fixture
def isolated_nonebot_plugin_state():
    """隔离会实际加载 NoneBot 插件的测试，并恢复原模块身份。"""
    from nonebot import matcher as nb_matcher
    from nonebot import plugin as nb_plugin
    from nonebot.plugin import manager as nb_manager

    def is_plugin_module(name: str) -> bool:
        return name == "packages" or name.startswith(("packages.", "nonebot_plugin_apscheduler", "pallas_plugin_"))

    module_snapshot = {name: module for name, module in sys.modules.items() if is_plugin_module(name)}
    parent_attrs: dict[tuple[str, str], tuple[bool, object | None]] = {}
    for name in module_snapshot:
        parent_name, _, child_name = name.rpartition(".")
        if not parent_name or parent_name not in module_snapshot:
            continue
        parent = module_snapshot[parent_name]
        if hasattr(parent, child_name):
            parent_attrs[(parent_name, child_name)] = (True, getattr(parent, child_name))
        else:
            parent_attrs[(parent_name, child_name)] = (False, None)
    saved_plugins = dict(nb_plugin._plugins)
    saved_managers = list(nb_plugin._managers)
    saved_matchers = {priority: list(items) for priority, items in nb_matcher.matchers.items()}
    saved_current_plugin = nb_manager._current_plugin.get()

    def clear_plugin_state() -> None:
        nb_plugin._plugins.clear()
        nb_plugin._managers.clear()
        nb_manager._current_plugin.set(None)

    def remove_plugin_modules() -> None:
        for name in list(sys.modules):
            if not is_plugin_module(name):
                continue
            module = sys.modules.pop(name)
            parent_name, _, child_name = name.rpartition(".")
            parent = sys.modules.get(parent_name)
            if parent is not None and getattr(parent, child_name, None) is module:
                delattr(parent, child_name)

    clear_plugin_state()
    remove_plugin_modules()
    try:
        yield
    finally:
        clear_plugin_state()
        remove_plugin_modules()
        sys.modules.update(module_snapshot)
        for (parent_name, child_name), (exists, value) in parent_attrs.items():
            parent = sys.modules.get(parent_name)
            if parent is None:
                continue
            if exists:
                setattr(parent, child_name, value)
            elif hasattr(parent, child_name):
                delattr(parent, child_name)
        nb_plugin._plugins.update(saved_plugins)
        nb_plugin._managers.extend(saved_managers)
        nb_manager._current_plugin.set(saved_current_plugin)
        nb_matcher.matchers.clear()
        nb_matcher.matchers.update({priority: list(items) for priority, items in saved_matchers.items()})


@pytest.fixture
async def pg_engine():
    """
    每个测试独占一个干净 schema。

    进入前：drop_all → init_pg，确保上一次遗留不影响当前用例。
    退出后：drop_all → dispose_pg，避免模块级缓存跨用例污染。
    """
    if not PG_TEST_DSN:
        pytest.skip("需要设置 PG_TEST_DSN 指向测试 PG 实例")

    from sqlalchemy.ext.asyncio import create_async_engine

    from pallas.core.foundation.db.repository_pg import Base, dispose_pg, init_pg

    engine = create_async_engine(PG_TEST_DSN)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await init_pg(engine)
    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await dispose_pg()


@pytest.fixture
async def pg_env(pg_engine):
    """
    迁移脚本集成测试用：在 pg_engine 基础上额外提供 session factory、
    迁移模块句柄、以及 PG 方言的 insert 构造器。
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.ext.asyncio import async_sessionmaker

    migrate = _load_migrate_module()
    await migrate._ensure_state_table(pg_engine)
    sf = async_sessionmaker(pg_engine, expire_on_commit=False)

    return {
        "engine": pg_engine,
        "sf": sf,
        "migrate": migrate,
        "pg_insert": pg_insert,
    }


def _load_migrate_module():
    """动态加载 tools/migrate_mongo_to_pg.py。"""
    mod_name = "_pallas_migrate_mongo_to_pg"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, _ROOT / "tools" / "migrate_mongo_to_pg.py")
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fake_coord_redis(monkeypatch):
    store: dict[str, str] = {}
    sets: dict[str, set[str]] = {}

    class FakePipeline:
        def __init__(self, outer: FakeRedis, *, transaction: bool = False) -> None:
            self.outer = outer
            self.ops: list[tuple[str, tuple, dict]] = []

        def __enter__(self) -> FakePipeline:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def watch(self, key: str) -> None:
            pass

        def unwatch(self) -> None:
            pass

        def setex(self, key: str, ttl: int, val: str) -> None:
            self.ops.append(("setex", (key, ttl, val), {}))

        def publish(self, channel: str, body: str) -> None:
            self.ops.append(("publish", (channel, body), {}))

        def multi(self) -> None:
            pass

        def delete(self, key: str) -> None:
            self.ops.append(("delete", (key,), {}))

        def execute(self) -> list[Any]:
            results: list[Any] = []
            for op, args, _kw in self.ops:
                if op == "setex":
                    results.append(self.outer.setex(*args))
                elif op == "publish":
                    results.append(self.outer.publish(*args))
                elif op == "delete":
                    results.append(self.outer.delete(*args))
            self.ops.clear()
            return results

    class FakeRedis:
        def get(self, key: str):
            return store.get(key)

        def setex(self, key: str, ttl: int, val: str) -> bool:
            store[key] = val
            return True

        def set(self, key: str, val: str, ex: int | None = None, nx: bool = False) -> bool:
            if nx and key in store:
                return False
            store[key] = val
            return True

        def delete(self, key: str) -> int:
            store.pop(key, None)
            sets.pop(key, None)
            return 1

        def publish(self, channel: str, body: str) -> int:
            return 1

        def pipeline(self, transaction: bool = True) -> FakePipeline:
            return FakePipeline(self, transaction=transaction)

        def scan(self, cursor: int = 0, match: str | None = None, count: int = 128):
            prefix = (match or "").rstrip("*")
            keys = sorted(k for k in store if k.startswith(prefix))
            return 0, keys

        def sismember(self, key: str, member: str) -> bool:
            return member in sets.get(key, set())

        def sadd(self, key: str, *members: str) -> int:
            bucket = sets.setdefault(key, set())
            before = len(bucket)
            bucket.update(members)
            return len(bucket) - before

        def expire(self, key: str, ttl: int) -> bool:
            return True

    client = FakeRedis()
    monkeypatch.setattr("pallas.core.platform.coord.redis_settings.coord_redis_enabled", lambda: True)
    monkeypatch.setattr("pallas.core.platform.coord.redis_claim.get_coord_redis_client", lambda: client)
    return store, client
