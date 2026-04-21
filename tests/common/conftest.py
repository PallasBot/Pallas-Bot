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

import pytest

PG_TEST_DSN = os.getenv("PG_TEST_DSN")
_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
async def pg_engine():
    """
    每个测试独占一个干净 schema。

    进入前：drop_all → init_pg，确保上一次遗留不影响当前用例。
    退出后：drop_all → dispose_pg（顺便清 _CONFIG_CACHES），避免模块级缓存跨用例污染。
    """
    if not PG_TEST_DSN:
        pytest.skip("需要设置 PG_TEST_DSN 指向测试 PG 实例")

    from sqlalchemy.ext.asyncio import create_async_engine

    from src.common.db.repository_pg import Base, dispose_pg, init_pg

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

    yield {
        "engine": pg_engine,
        "sf": sf,
        "migrate": migrate,
        "pg_insert": pg_insert,
    }


def _load_migrate_module():
    """动态加载 tools/migrate_mongo_to_pg.py（非 package，只能按路径 import）。"""
    mod_name = "_pallas_migrate_mongo_to_pg"
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(
        mod_name, _ROOT / "tools" / "migrate_mongo_to_pg.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod
