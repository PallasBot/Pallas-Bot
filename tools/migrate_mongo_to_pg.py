#!/usr/bin/env python3
"""
MongoDB → PostgreSQL 迁移脚本

迁移范围：Context、Message、BlackList、BotConfig、GroupConfig、UserConfig、ImageCache

用法：
    uv run --extra pg python tools/migrate_mongo_to_pg.py

选项：
    --batch N       每批处理条数，默认 1000
    --dry-run       只统计数量，不写入 PostgreSQL
    --pg-db NAME    目标 PostgreSQL 数据库名，默认读取 PG_DB 环境变量（fallback: PallasBot）
    --tables TABLE  仅迁移指定表（可多选），可选值：
                      context message blacklist botconfig groupconfig userconfig imagecache

示例：
    # 全量迁移
    uv run --extra pg python tools/migrate_mongo_to_pg.py

    # 指定目标数据库名
    uv run --extra pg python tools/migrate_mongo_to_pg.py --pg-db MyBot

    # 仅迁移消息和上下文，每批 500 条
    uv run --extra pg python tools/migrate_mongo_to_pg.py --tables context message --batch 500

    # 预演（不写入数据库）
    uv run --extra pg python tools/migrate_mongo_to_pg.py --dry-run

环境变量（从 .env 读取，也可手动设置）：
    MONGO_HOST / MONGO_PORT / MONGO_USER / MONGO_PASSWORD
    PG_HOST / PG_PORT / PG_USER / PG_PASSWORD / PG_DB
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

ALL_TABLES = ["context", "message", "blacklist", "botconfig", "groupconfig", "userconfig", "imagecache"]

# asyncpg 单语句参数上限 32767
_ANS_BATCH = 6000  # ContextAnswerRow    5 列
_MSG_BATCH = 16000  # ContextAnswerMsg    2 列
_BAN_BATCH = 6000  # ContextBanRow       5 列
_IC_BATCH = 6000  # ImageCacheRow       4 列
_MSG_ROW_BATCH = 4000  # MessageRow       8 列


def _mongo_dsn() -> str:
    h, p = os.getenv("MONGO_HOST", "127.0.0.1"), int(os.getenv("MONGO_PORT", "27017"))
    u, pw = os.getenv("MONGO_USER", ""), os.getenv("MONGO_PASSWORD", "")
    return f"mongodb://{quote_plus(u)}:{quote_plus(pw)}@{h}:{p}" if u and pw else f"mongodb://{h}:{p}"


def _pg_dsn() -> str:
    h = os.getenv("PG_HOST", os.getenv("MONGO_HOST", "127.0.0.1"))
    p = int(os.getenv("PG_PORT", "5432"))
    u, pw = os.getenv("PG_USER", ""), os.getenv("PG_PASSWORD", "")
    db = os.getenv("PG_DB", "PallasBot")
    auth = f"{quote_plus(u)}:{quote_plus(pw)}@" if u and pw else ""
    return f"postgresql+asyncpg://{auth}{h}:{p}/{db}"


def _strip_null(obj):
    """递归去除 PostgreSQL 不支持的 \\u0000 字符"""
    if isinstance(obj, str):
        return obj.replace("\x00", "")
    if isinstance(obj, dict):
        return {k: _strip_null(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_null(i) for i in obj]
    return obj


def _kw_hash(keywords: str) -> str:
    import hashlib

    return hashlib.md5(keywords.encode("utf-8", errors="replace")).hexdigest()


async def _ensure_db() -> None:
    import re

    import asyncpg

    h = os.getenv("PG_HOST", os.getenv("MONGO_HOST", "127.0.0.1"))
    p = int(os.getenv("PG_PORT", "5432"))
    u, pw = os.getenv("PG_USER", "") or None, os.getenv("PG_PASSWORD", "") or None
    db = os.getenv("PG_DB", "PallasBot")
    if not re.match(r"^[A-Za-z0-9_\-]+$", db):
        raise ValueError(f"非法数据库名: {db!r}")
    conn = await asyncpg.connect(host=h, port=p, user=u, password=pw, database="postgres")
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", db):
            await conn.execute(f'CREATE DATABASE "{db}"')
            print(f"已创建数据库 {db}")
        else:
            print(f"数据库 {db} 已存在")
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# 各表迁移函数
# ---------------------------------------------------------------------------


async def _migrate_context(Context, sf, ContextRow, AnsRow, AnsMsgRow, BanRow, ins, batch_size, dry_run):
    from sqlalchemy import delete as D
    from sqlalchemy import select as S

    total = await Context.count()
    print(f"\n📦 Context: {total} 条")
    migrated = skip = 0

    while True:
        batch = await Context.find_all().skip(skip).limit(batch_size).to_list()
        if not batch:
            break

        seen: dict[str, tuple] = {}
        for doc in batch:
            h = _kw_hash(doc.keywords)
            seen[h] = (
                doc,
                {
                    "keywords": _strip_null(doc.keywords),
                    "keywords_hash": h,
                    "time": doc.time,
                    "trigger_count": doc.trigger_count,
                    "clear_time": doc.clear_time,
                },
            )

        if not dry_run:
            async with sf() as session:
                stmt = ins(ContextRow).values([v[1] for v in seen.values()])
                await session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=["keywords_hash"],
                        set_={
                            "keywords": stmt.excluded.keywords,
                            "time": stmt.excluded.time,
                            "trigger_count": stmt.excluded.trigger_count,
                            "clear_time": stmt.excluded.clear_time,
                        },
                    )
                )
                await session.commit()

                result = await session.execute(
                    S(ContextRow.id, ContextRow.keywords_hash).where(ContextRow.keywords_hash.in_(seen.keys()))
                )
                h2id = {r.keywords_hash: r.id for r in result}
                ctx_ids = list(h2id.values())
                await session.execute(D(AnsRow).where(AnsRow.context_id.in_(ctx_ids)))
                await session.execute(D(BanRow).where(BanRow.context_id.in_(ctx_ids)))

                ans_data, ban_rows = [], []
                for h, (doc, _) in seen.items():
                    cid = h2id.get(h)
                    if cid is None:
                        continue
                    for a in doc.answers:
                        ans_data.append({
                            "context_id": cid,
                            "keywords": _strip_null(a.keywords),
                            "group_id": a.group_id,
                            "count": a.count,
                            "time": a.time,
                            "_msgs": [_strip_null(m) for m in a.messages],
                        })
                    for b in doc.ban:
                        ban_rows.append({
                            "context_id": cid,
                            "keywords": _strip_null(b.keywords),
                            "group_id": b.group_id,
                            "reason": _strip_null(b.reason),
                            "time": b.time,
                        })

                if ans_data:
                    no_msg = [{k: v for k, v in d.items() if k != "_msgs"} for d in ans_data]
                    lookup: dict[tuple, list[int]] = {}
                    for i in range(0, len(no_msg), _ANS_BATCH):
                        ret = await session.execute(
                            ins(AnsRow)
                            .values(no_msg[i : i + _ANS_BATCH])
                            .returning(AnsRow.id, AnsRow.context_id, AnsRow.group_id, AnsRow.keywords)
                        )
                        for r in ret.fetchall():
                            lookup.setdefault((r.context_id, r.group_id, r.keywords), []).append(r.id)

                    msg_rows = []
                    for d in ans_data:
                        ids = lookup.get((d["context_id"], d["group_id"], d["keywords"]), [])
                        if ids:
                            aid = ids.pop(0)
                            msg_rows.extend({"answer_id": aid, "message": m} for m in d["_msgs"])
                    for i in range(0, len(msg_rows), _MSG_BATCH):
                        await session.execute(ins(AnsMsgRow).values(msg_rows[i : i + _MSG_BATCH]))

                for i in range(0, len(ban_rows), _BAN_BATCH):
                    await session.execute(ins(BanRow).values(ban_rows[i : i + _BAN_BATCH]))
                await session.commit()

        migrated += len(batch)
        skip += batch_size
        print(f"  Context {migrated}/{total}", end="\r")
    print(f"  Context {migrated}/{total} ✓")


async def _migrate_message(Message, sf, MsgRow, ins, batch_size, dry_run):
    col = Message.get_pymongo_collection()
    total = await col.count_documents({})
    print(f"\n📦 Message: {total} 条")
    migrated, batch = 0, []

    async for doc in col.find({}, batch_size=batch_size):
        raw = doc.get("raw_message", "")
        batch.append(
            _strip_null({
                "group_id": int(doc.get("group_id", 0)),
                "user_id": int(doc.get("user_id", 0)),
                "bot_id": int(doc.get("bot_id", 0)),
                "raw_message": raw,
                "is_plain_text": doc.get("is_plain_text", True),
                "plain_text": doc.get("plain_text", raw),
                "keywords": doc.get("keywords", ""),
                "time": doc.get("time", 0),
            })
        )
        if len(batch) >= _MSG_ROW_BATCH:
            if not dry_run:
                async with sf() as session:
                    await session.execute(ins(MsgRow).values(batch).on_conflict_do_nothing())
                    await session.commit()
            migrated += len(batch)
            batch = []
            print(f"  Message {migrated}/{total}", end="\r")

    if batch:
        if not dry_run:
            async with sf() as session:
                await session.execute(ins(MsgRow).values(batch).on_conflict_do_nothing())
                await session.commit()
        migrated += len(batch)
    print(f"  Message {migrated}/{total} ✓")


async def _migrate_blacklist(BlackList, sf, BLRow, ins, dry_run):
    total = await BlackList.count()
    print(f"\n📦 BlackList: {total} 条")
    docs = await BlackList.find_all().to_list()
    if not docs:
        print("  BlackList 0/0 ✓")
        return
    rows = [
        _strip_null({"group_id": int(d.group_id), "answers": d.answers, "answers_reserve": d.answers_reserve})
        for d in docs
    ]
    if not dry_run:
        async with sf() as session:
            stmt = ins(BLRow).values(rows)
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["group_id"],
                    set_={"answers": stmt.excluded.answers, "answers_reserve": stmt.excluded.answers_reserve},
                )
            )
            await session.commit()
    print(f"  BlackList {len(docs)}/{total} ✓")


async def _migrate_bot_config(BotConfigModule, sf, BCRow, ins, dry_run):
    col = BotConfigModule.get_pymongo_collection()
    total = await col.count_documents({})
    print(f"\n📦 BotConfig: {total} 条")
    raw_docs = await col.find({}).to_list(length=None)
    if not raw_docs:
        print("  BotConfig 0/0 ✓")
        return

    rows = []
    for raw in raw_docs:
        try:
            if "auto_accept" in raw and "auto_accept_group" not in raw:
                ag, af = bool(raw["auto_accept"]), False
            else:
                ag = bool(raw.get("auto_accept_group", False))
                af = bool(raw.get("auto_accept_friend", False))
            admins = []
            for x in raw.get("admins", []):
                try:
                    admins.append(int(x))
                except (TypeError, ValueError):
                    print(f"  ⚠️  BotConfig account={raw.get('account')} admins 跳过无效值: {x!r}")
            tn = raw.get("taken_name", {})
            dk = raw.get("drunk", {})
            rows.append(
                _strip_null({
                    "account": int(raw["account"]),
                    "admins": admins,
                    "auto_accept_friend": af,
                    "auto_accept_group": ag,
                    "security": bool(raw.get("security", False)),
                    "taken_name": {str(k): v for k, v in (tn.items() if isinstance(tn, dict) else {})},
                    "drunk": {str(k): v for k, v in (dk.items() if isinstance(dk, dict) else {})},
                    "disabled_plugins": raw.get("disabled_plugins", []),
                })
            )
        except Exception as e:
            print(f"  ⚠️  BotConfig 跳过 account={raw.get('account')}: {e}")

    if not dry_run:
        async with sf() as session:
            stmt = ins(BCRow).values(rows)
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["account"],
                    set_={
                        f: getattr(stmt.excluded, f)
                        for f in [
                            "admins",
                            "auto_accept_friend",
                            "auto_accept_group",
                            "security",
                            "taken_name",
                            "drunk",
                            "disabled_plugins",
                        ]
                    },
                )
            )
            await session.commit()
    print(f"  BotConfig {len(rows)}/{total} ✓")


async def _migrate_group_config(GroupConfigModule, sf, GCRow, ins, dry_run):
    total = await GroupConfigModule.count()
    print(f"\n📦 GroupConfig: {total} 条")
    docs = await GroupConfigModule.find_all().to_list()
    if not docs:
        print("  GroupConfig 0/0 ✓")
        return
    rows = [
        _strip_null({
            "group_id": int(d.group_id),
            "roulette_mode": d.roulette_mode,
            "banned": d.banned,
            "sing_progress": json.loads(d.sing_progress.model_dump_json()) if d.sing_progress else None,
            "disabled_plugins": d.disabled_plugins,
        })
        for d in docs
    ]
    if not dry_run:
        async with sf() as session:
            stmt = ins(GCRow).values(rows)
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["group_id"],
                    set_={
                        f: getattr(stmt.excluded, f)
                        for f in ["roulette_mode", "banned", "sing_progress", "disabled_plugins"]
                    },
                )
            )
            await session.commit()
    print(f"  GroupConfig {len(docs)}/{total} ✓")


async def _migrate_user_config(UserConfigModule, sf, UCRow, ins, batch_size, dry_run):
    total = await UserConfigModule.count()
    print(f"\n📦 UserConfig: {total} 条")
    migrated = skip = 0
    while True:
        batch = await UserConfigModule.find_all().skip(skip).limit(batch_size).to_list()
        if not batch:
            break
        rows = [_strip_null({"user_id": int(d.user_id), "banned": d.banned}) for d in batch]
        if not dry_run:
            async with sf() as session:
                stmt = ins(UCRow).values(rows)
                await session.execute(
                    stmt.on_conflict_do_update(index_elements=["user_id"], set_={"banned": stmt.excluded.banned})
                )
                await session.commit()
        migrated += len(batch)
        skip += batch_size
        print(f"  UserConfig {migrated}/{total}", end="\r")
    print(f"  UserConfig {migrated}/{total} ✓")


async def _migrate_image_cache(ImageCache, sf, ICRow, ins, batch_size, dry_run):
    col = ImageCache.get_pymongo_collection()
    total = await col.count_documents({})
    print(f"\n📦 ImageCache: {total} 条")
    migrated, batch = 0, []

    async for doc in col.find({}, batch_size=batch_size):
        batch.append(
            _strip_null({
                "cq_code": doc.get("cq_code", ""),
                "base64_data": doc.get("base64_data"),
                "ref_times": int(doc.get("ref_times", 1)),
                "date": int(doc.get("date", 0)),
            })
        )
        if len(batch) >= _IC_BATCH:
            if not dry_run:
                async with sf() as session:
                    stmt = ins(ICRow).values(batch)
                    await session.execute(
                        stmt.on_conflict_do_update(
                            index_elements=["cq_code"],
                            set_={f: getattr(stmt.excluded, f) for f in ["base64_data", "ref_times", "date"]},
                        )
                    )
                    await session.commit()
            migrated += len(batch)
            batch = []
            print(f"  ImageCache {migrated}/{total}", end="\r")

    if batch:
        if not dry_run:
            async with sf() as session:
                stmt = ins(ICRow).values(batch)
                await session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=["cq_code"],
                        set_={f: getattr(stmt.excluded, f) for f in ["base64_data", "ref_times", "date"]},
                    )
                )
                await session.commit()
        migrated += len(batch)
    print(f"  ImageCache {migrated}/{total} ✓")


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


async def migrate(batch_size: int, dry_run: bool, tables: set[str], pg_db: str | None = None) -> None:
    if pg_db:
        os.environ["PG_DB"] = pg_db
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
    except ImportError:
        print("❌ 缺少 SQLAlchemy/asyncpg，请执行：uv sync --extra pg")
        sys.exit(1)

    from beanie import init_beanie
    from pymongo import AsyncMongoClient
    from sqlalchemy import text as T
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from src.common.db.modules import (
        BlackList,
        BotConfigModule,
        Context,
        GroupConfigModule,
        ImageCache,
        Message,
        UserConfigModule,
    )
    from src.common.db.repository_pg import (
        BlackListRow,
        BotConfigRow,
        ContextAnswerMessageRow,
        ContextAnswerRow,
        ContextBanRow,
        ContextRow,
        GroupConfigRow,
        ImageCacheRow,
        MessageRow,
        UserConfigRow,
        init_pg,
    )

    print(f"🔗 连接 MongoDB: {_mongo_dsn()}")
    mongo_client = AsyncMongoClient(_mongo_dsn(), unicode_decode_error_handler="ignore")
    await init_beanie(
        database=mongo_client["PallasBot"],
        document_models=[Context, Message, BlackList, BotConfigModule, GroupConfigModule, UserConfigModule, ImageCache],
    )

    print(f"🔗 连接 PostgreSQL: {_pg_dsn()}")
    if not dry_run:
        await _ensure_db()

    engine = create_async_engine(_pg_dsn(), echo=False)
    if not dry_run:
        await init_pg(engine)
        async with engine.begin() as conn:
            # 删除旧的 keywords 唯一约束（超长值会超出 btree 2704 字节限制）
            await conn.execute(T("ALTER TABLE context DROP CONSTRAINT IF EXISTS context_keywords_key"))
            await conn.execute(T("DROP INDEX IF EXISTS ix_context_keywords"))
            await conn.execute(T("ALTER TABLE context ADD COLUMN IF NOT EXISTS keywords_hash TEXT"))
            await conn.execute(T("UPDATE context SET keywords_hash = md5(keywords) WHERE keywords_hash IS NULL"))
            await conn.execute(T("ALTER TABLE context ALTER COLUMN keywords_hash SET NOT NULL"))
            await conn.execute(
                T("CREATE UNIQUE INDEX IF NOT EXISTS ix_context_keywords_hash ON context (keywords_hash)")
            )

    sf = async_sessionmaker(engine, expire_on_commit=False)

    if "context" in tables:
        await _migrate_context(
            Context,
            sf,
            ContextRow,
            ContextAnswerRow,
            ContextAnswerMessageRow,
            ContextBanRow,
            pg_insert,
            batch_size,
            dry_run,
        )
    if "message" in tables:
        await _migrate_message(Message, sf, MessageRow, pg_insert, batch_size, dry_run)
    if "blacklist" in tables:
        await _migrate_blacklist(BlackList, sf, BlackListRow, pg_insert, dry_run)
    if "botconfig" in tables:
        await _migrate_bot_config(BotConfigModule, sf, BotConfigRow, pg_insert, dry_run)
    if "groupconfig" in tables:
        await _migrate_group_config(GroupConfigModule, sf, GroupConfigRow, pg_insert, dry_run)
    if "userconfig" in tables:
        await _migrate_user_config(UserConfigModule, sf, UserConfigRow, pg_insert, batch_size, dry_run)
    if "imagecache" in tables:
        await _migrate_image_cache(ImageCache, sf, ImageCacheRow, pg_insert, batch_size, dry_run)

    await engine.dispose()
    print("\n✅ 迁移完成")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="MongoDB → PostgreSQL 数据迁移",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"可迁移的表：{', '.join(ALL_TABLES)}",
    )
    parser.add_argument("--batch", type=int, default=1000, metavar="N", help="每批处理条数（默认 1000）")
    parser.add_argument("--dry-run", action="store_true", help="只统计数量，不写入 PostgreSQL")
    parser.add_argument("--pg-db", metavar="NAME", help="目标 PostgreSQL 数据库名（覆盖 PG_DB 环境变量）")
    parser.add_argument(
        "--tables", nargs="+", choices=ALL_TABLES, metavar="TABLE", help="仅迁移指定表（空格分隔），不指定则迁移全部"
    )
    args = parser.parse_args()

    selected = set(args.tables) if args.tables else set(ALL_TABLES)
    if args.dry_run:
        print("⚠️  dry-run 模式，不会写入 PostgreSQL")
    if args.tables:
        print(f"📋 仅迁移：{', '.join(t for t in ALL_TABLES if t in selected)}")

    asyncio.run(migrate(args.batch, args.dry_run, selected, args.pg_db))
