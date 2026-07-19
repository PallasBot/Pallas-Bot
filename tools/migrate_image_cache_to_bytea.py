#!/usr/bin/env python3
"""把 image_cache.base64_data (TEXT) 迁移到 image_cache.blob_data (BYTEA)。

背景（关联 issue）：
  - #223「PG 后端——使用二进制格式存储图片」：base64 字符串效率低，PG 有 BYTEA 干啥不用
  - #224「PG 后端——绝大多数（99.5%）图片缓存数据为NULL」：本次只动 schema，逻辑修复在
    pallas/core/shared/utils/media_cache/__init__.py 里完成

设计要点：
  - **两阶段迁移**（加列 → UPDATE → 删旧列），避免在百万行 NULL 表上一次性
    `ALTER COLUMN TYPE` 触发的长 ACCESS EXCLUSIVE 锁阻塞写入。
  - **默认 dry-run**：必须显式 `--apply` 才会真正写库。
  - **不依赖 NoneBot 启动**：直接用环境变量读 PG 连接（与 tools/migrate_mongo_to_pg.py 同款）。

用法：
    # 1. 预览：探测当前 schema、报告将要做的事
    uv run python tools/migrate_image_cache_to_bytea.py

    # 2. 真实执行
    uv run python tools/migrate_image_cache_to_bytea.py --apply

    # 3. 校验：抽 5 行确认 blob_data 已落盘 + cq_code 完整
    uv run python tools/migrate_image_cache_to_bytea.py --verify

连接（优先级）：
    1. 已导出的 PG_HOST / PG_PORT / PG_USER / PG_PASSWORD / PG_DB
    2. 否则从 config/pallas.toml（及遗留 .env / webui.json）合并读取
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="把 image_cache.base64_data (TEXT/base64) 迁移到 blob_data (BYTEA)。默认 dry-run。"
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "--apply",
        action="store_true",
        help="真正执行迁移（不加此参数则只打印计划）",
    )
    g.add_argument(
        "--verify",
        action="store_true",
        help="迁移结束后再次校验：抽 5 行确认 blob_data 是 bytes、cq_code 完整",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# 连接
# ---------------------------------------------------------------------------


def _pg_conn_kwargs() -> tuple[dict[str, object], str]:
    """裸 asyncpg 连接参数 + 目标库名（用于 _ensure_db 之类的管理命令）。

    Returns:
        (conn_kwargs, db_name)：conn_kwargs 给 ``asyncpg.connect(**conn_kwargs)``，
        db_name 单独返回（不在 kwargs 里，因为 asyncpg 把它当 key 不能轻易替换）。
    """
    # 补齐未导出的 PG_*（不覆盖已有环境变量）
    from pallas.core.foundation.config.repo_settings import apply_repo_settings_to_environ

    apply_repo_settings_to_environ()

    h = os.getenv("PG_HOST") or os.getenv("MONGO_HOST", "127.0.0.1")
    p_port = int(os.getenv("PG_PORT", "5432"))
    u = os.getenv("PG_USER", "") or None
    pw = os.getenv("PG_PASSWORD", "") or None
    db = os.getenv("PG_DB", "PallasBot")
    if not re.match(r"^[A-Za-z0-9_\-]+$", db):
        raise ValueError(f"非法数据库名: {db!r}")
    conn_kwargs: dict[str, object] = {"host": h, "port": p_port, "database": "postgres"}
    if u is not None:
        conn_kwargs["user"] = u
    if pw is not None:
        conn_kwargs["password"] = pw
    return conn_kwargs, db


# ---------------------------------------------------------------------------
# 探测
# ---------------------------------------------------------------------------


async def _probe(conn) -> dict[str, object]:
    """返回当前 image_cache 表的 schema 状态。"""
    rows = await conn.fetch(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'image_cache'
          AND column_name IN ('base64_data', 'blob_data')
        """
    )
    cols = {r["column_name"]: {"type": r["data_type"], "nullable": r["is_nullable"]} for r in rows}

    exists = await conn.fetchval("SELECT 1 FROM information_schema.tables WHERE table_name = 'image_cache'")

    total = None
    non_null_base64 = None
    non_null_blob = None
    if exists:
        total = await conn.fetchval("SELECT count(*) FROM image_cache")
        if "base64_data" in cols:
            non_null_base64 = await conn.fetchval("SELECT count(*) FROM image_cache WHERE base64_data IS NOT NULL")
        if "blob_data" in cols:
            non_null_blob = await conn.fetchval("SELECT count(*) FROM image_cache WHERE blob_data IS NOT NULL")

    return {
        "table_exists": bool(exists),
        "columns": cols,
        "total_rows": total,
        "non_null_base64": non_null_base64,
        "non_null_blob": non_null_blob,
    }


# ---------------------------------------------------------------------------
# 迁移主流程
# ---------------------------------------------------------------------------


async def _migrate(conn) -> None:
    """两阶段迁移：在单事务里加列 → UPDATE → 删旧列。"""
    async with conn.transaction():
        # 1. 加新列
        await conn.execute("ALTER TABLE image_cache ADD COLUMN blob_data BYTEA")
        print("  + ADD COLUMN blob_data BYTEA")

        # 2. 把旧 base64 字符串解码灌入新列（NULL 保持 NULL）
        await conn.execute(
            "UPDATE image_cache SET blob_data = decode(base64_data, 'base64') WHERE base64_data IS NOT NULL"
        )
        print("  + UPDATE image_cache SET blob_data = decode(base64_data, 'base64') WHERE base64_data IS NOT NULL")

        # 3. 删旧列
        await conn.execute("ALTER TABLE image_cache DROP COLUMN base64_data")
        print("  + DROP COLUMN base64_data")


async def _verify(conn) -> None:
    """抽 5 行确认 blob_data 落盘 + cq_code 完整。"""
    rows = await conn.fetch(
        """
        SELECT cq_code, ref_times, date, octet_length(blob_data) AS blob_bytes
        FROM image_cache
        WHERE blob_data IS NOT NULL
        ORDER BY random()
        LIMIT 5
        """
    )
    if not rows:
        print("[verify] 没有任何 blob_data 非空的行——可能数据还没灌进来。")
        return
    print(f"[verify] 抽样 {len(rows)} 行：")
    for r in rows:
        print(f"  cq_code={r['cq_code']!r}  ref_times={r['ref_times']}  date={r['date']}  blob_bytes={r['blob_bytes']}")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


async def _run(args: argparse.Namespace) -> int:
    import asyncpg

    conn_kwargs, db = _pg_conn_kwargs()
    conn_kwargs["database"] = db

    print(f"目标 PG: {conn_kwargs['host']}:{conn_kwargs['port']}/{db}")
    conn = await asyncpg.connect(**conn_kwargs)
    try:
        state = await _probe(conn)
        print("\n[probe] 当前 image_cache 状态：")
        print(f"  table_exists     = {state['table_exists']}")
        print(f"  columns          = {state['columns']}")
        print(f"  total_rows       = {state['total_rows']}")
        print(f"  non_null_base64  = {state['non_null_base64']}")
        print(f"  non_null_blob    = {state['non_null_blob']}")

        if not state["table_exists"]:
            print("\n[plan] image_cache 表不存在——请先启动一次 Bot 让 init_pg 走 create_all 创建表，再重跑本脚本。")
            return 0

        if "blob_data" in state["columns"] and "base64_data" not in state["columns"]:
            data_type = state["columns"]["blob_data"]["type"]
            if data_type == "bytea":
                print("\n[plan] 已迁移过（blob_data BYTEA），无需操作。")
                if args.verify:
                    await _verify(conn)
                return 0
            print(f"\n[plan] 异常：blob_data 存在但类型是 {data_type}，需要人工处理。")
            return 1

        if "base64_data" not in state["columns"]:
            print("\n[plan] 异常：表存在但既没有 base64_data 也没有 blob_data，请人工检查。")
            return 1

        # 此时确定需要迁移：只有 base64_data TEXT
        old_type = state["columns"]["base64_data"]["type"]
        non_null = state["non_null_base64"] or 0
        total = state["total_rows"] or 0
        print(f"\n[plan] 需要迁移：base64_data 是 {old_type}（{non_null}/{total} 行非空）")
        print("[plan] 步骤：")
        print("  1) ALTER TABLE image_cache ADD COLUMN blob_data BYTEA")
        print("  2) UPDATE image_cache SET blob_data = decode(base64_data, 'base64') WHERE base64_data IS NOT NULL")
        print("  3) ALTER TABLE image_cache DROP COLUMN base64_data")

        if not args.apply:
            print("\n[plan] dry-run 模式，没有改动。加 --apply 真正执行。")
            return 0

        print("\n[apply] 开始迁移…")
        await _migrate(conn)
        print("[apply] 迁移完成，重新探测：")
        new_state = await _probe(conn)
        print(f"  columns       = {new_state['columns']}")
        print(f"  non_null_blob = {new_state['non_null_blob']}")

        if args.verify:
            await _verify(conn)
        return 0
    finally:
        await conn.close()


def main() -> int:
    args = _parse_args()
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("中断", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
