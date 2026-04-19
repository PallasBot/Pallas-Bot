#!/usr/bin/env python3
"""
MongoDB → PostgreSQL 迁移脚本

迁移范围：Context、Message、BlackList、BotConfig、GroupConfig、UserConfig、ImageCache

特性：
- 基于 Mongo `_id` 游标流式读取，不走 skip/limit，千万级数据也不会退化成 O(n)
- migration_state 表记录每张表的 last_id；中断后重跑自动断点续传，不会重复写入
- 批级 commit 与 migration_state 在同一事务内原子写入，保证"恰好一次"
- 逐条 defensive 解析，脏数据（缺字段 / 非法类型 / NUL 字符）跳过并计入汇总，不阻断
- Context 聚合同 batch 内相同 keywords_hash 的 answers / bans，不再丢数据
- upsert 依赖 `repository_pg` 里定义的唯一约束（含复合 upsert_answer 约束），新字段自动加到 PG

用法：
    uv run --extra pg python tools/migrate_mongo_to_pg.py

选项：
    --batch N       每批处理条数，默认 1000
    --dry-run       只统计数量，不写入 PostgreSQL
    --pg-db NAME    目标 PG 库名，覆盖 PG_DB 环境变量
    --mongo-db NAME 源 Mongo 库名，覆盖 MONGO_DB 环境变量（默认 PallasBot）
    --tables TABLE  仅迁移指定表，可选：context message blacklist botconfig groupconfig userconfig imagecache
    --restart       清空 migration_state 重新从头迁移

示例：
    # 全量迁移（自动续传）
    uv run --extra pg python tools/migrate_mongo_to_pg.py

    # 指定目标库
    uv run --extra pg python tools/migrate_mongo_to_pg.py --pg-db MyBot --mongo-db PallasBot

    # 仅迁移 context 和 message，批量 500
    uv run --extra pg python tools/migrate_mongo_to_pg.py --tables context message --batch 500

    # 预演
    uv run --extra pg python tools/migrate_mongo_to_pg.py --dry-run

    # 重新迁移（清空 state）
    uv run --extra pg python tools/migrate_mongo_to_pg.py --restart

环境变量（从 .env 读取，也可手动设置）：
    MONGO_HOST / MONGO_PORT / MONGO_USER / MONGO_PASSWORD / MONGO_DB
    PG_HOST / PG_PORT / PG_USER / PG_PASSWORD / PG_DB
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
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
_ANS_BATCH = 5000  # ContextAnswerRow    6 列（含 keywords_hash）
_MSG_BATCH = 16000  # ContextAnswerMessageRow 2 列
_BAN_BATCH = 6000  # ContextBanRow       5 列
_IC_BATCH = 6000  # ImageCacheRow       4 列
_MSG_ROW_BATCH = 4000  # MessageRow          8 列


# ---------------------------------------------------------------------------
# 通用工具 / defensive helpers
# ---------------------------------------------------------------------------


@dataclass
class _TableStats:
    """单表迁移摘要，脏数据跳过时计入 failed。"""

    total: int = 0
    migrated: int = 0
    skipped: int = 0
    failed: int = 0
    warnings: list[str] = field(default_factory=list)

    def warn(self, msg: str) -> None:
        self.failed += 1
        if len(self.warnings) < 20:
            self.warnings.append(msg)


def _as_int(x: Any, default: int = 0) -> int:
    if isinstance(x, bool):
        return int(x)
    if isinstance(x, int):
        return x
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def _as_str(x: Any, default: str = "") -> str:
    if x is None:
        return default
    if isinstance(x, str):
        return x
    return str(x)


def _as_bool(x: Any, default: bool = False) -> bool:
    if isinstance(x, bool):
        return x
    if x is None:
        return default
    if isinstance(x, (int, float)):
        return bool(x)
    if isinstance(x, str):
        return x.strip().lower() in ("true", "1", "yes", "y", "on")
    return default


def _as_list(x: Any) -> list:
    if isinstance(x, list):
        return x
    if x is None:
        return []
    # tuple / set 也视为可迭代
    if isinstance(x, (tuple, set)):
        return list(x)
    return []


def _as_dict(x: Any) -> dict:
    return x if isinstance(x, dict) else {}


def _strip_null(obj: Any) -> Any:
    """递归剥除 PostgreSQL TEXT 不接受的 \\x00 字节。"""
    if isinstance(obj, str):
        return obj.replace("\x00", "") if "\x00" in obj else obj
    if isinstance(obj, dict):
        return {k: _strip_null(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_null(i) for i in obj]
    return obj


def _kw_hash(keywords: str) -> str:
    # 与 repository_pg.keywords_hash 保持一致：先 strip \x00 再哈希
    clean = keywords.replace("\x00", "") if keywords and "\x00" in keywords else keywords
    return hashlib.md5((clean or "").encode("utf-8", errors="replace")).hexdigest()


def _mongo_dsn() -> str:
    h, p = os.getenv("MONGO_HOST", "127.0.0.1"), int(os.getenv("MONGO_PORT", "27017"))
    u, pw = os.getenv("MONGO_USER", ""), os.getenv("MONGO_PASSWORD", "")
    return f"mongodb://{quote_plus(u)}:{quote_plus(pw)}@{h}:{p}" if u and pw else f"mongodb://{h}:{p}"


def _mongo_db_name() -> str:
    return os.getenv("MONGO_DB") or "PallasBot"


def _pg_dsn() -> str:
    h = os.getenv("PG_HOST") or os.getenv("MONGO_HOST", "127.0.0.1")
    p = int(os.getenv("PG_PORT", "5432"))
    u, pw = os.getenv("PG_USER", ""), os.getenv("PG_PASSWORD", "")
    db = os.getenv("PG_DB", "PallasBot")
    auth = f"{quote_plus(u)}:{quote_plus(pw)}@" if u and pw else ""
    return f"postgresql+asyncpg://{auth}{h}:{p}/{db}"


async def _ensure_db() -> None:
    import asyncpg

    h = os.getenv("PG_HOST") or os.getenv("MONGO_HOST", "127.0.0.1")
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
# migration_state：断点续传
# ---------------------------------------------------------------------------


async def _ensure_state_table(engine) -> None:
    from sqlalchemy import text as T

    async with engine.begin() as conn:
        await conn.execute(
            T(
                """
                CREATE TABLE IF NOT EXISTS migration_state (
                    table_name TEXT PRIMARY KEY,
                    last_id TEXT NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )


async def _reset_state(engine) -> None:
    from sqlalchemy import text as T

    async with engine.begin() as conn:
        await conn.execute(T("DELETE FROM migration_state"))
    print("已清空 migration_state，将从头迁移")


async def _get_state(session, table: str) -> str | None:
    from sqlalchemy import text as T

    result = await session.execute(
        T("SELECT last_id FROM migration_state WHERE table_name = :t"), {"t": table}
    )
    return result.scalar_one_or_none()


async def _set_state(session, table: str, last_id: str) -> None:
    from sqlalchemy import text as T

    await session.execute(
        T(
            """
            INSERT INTO migration_state (table_name, last_id, updated_at)
            VALUES (:t, :id, NOW())
            ON CONFLICT (table_name) DO UPDATE
                SET last_id = EXCLUDED.last_id, updated_at = NOW()
            """
        ),
        {"t": table, "id": last_id},
    )


# ---------------------------------------------------------------------------
# Mongo 游标流式工具
# ---------------------------------------------------------------------------


def _oid(s: str | None):
    """字符串 _id 转为 ObjectId（如果可能）。非合法 ObjectId 当字符串用。"""
    from bson import ObjectId

    if s is None:
        return None
    try:
        return ObjectId(s)
    except Exception:
        return s


async def _stream_batches(col, last_id_str: str | None, batch_size: int):
    """按 _id 递增游标分批 yield Mongo 文档，返回 (batch_docs, last_id_str)。"""
    last_id = _oid(last_id_str)
    while True:
        q: dict[str, Any] = {}
        if last_id is not None:
            q["_id"] = {"$gt": last_id}
        cursor = col.find(q).sort("_id", 1).limit(batch_size)
        batch = await cursor.to_list(length=batch_size)
        if not batch:
            return
        yield batch
        last_id = batch[-1].get("_id")
        if len(batch) < batch_size:
            return


# ---------------------------------------------------------------------------
# Context 迁移（支持 batch 内 keywords 合并）
# ---------------------------------------------------------------------------


def _prepare_context_batch(docs: list[dict], stats: _TableStats) -> dict[str, dict]:
    """batch 内按 keywords_hash 合并，返回 hash -> {ctx fields, answers, bans}"""
    merged: dict[str, dict] = {}
    for doc in docs:
        try:
            kw = _as_str(doc.get("keywords"))
            if not kw:
                stats.warn(f"context skipped: empty keywords, _id={doc.get('_id')}")
                continue
            h = _kw_hash(kw)
            time_v = _as_int(doc.get("time"))
            # 兼容 Beanie alias："count" 或 "trigger_count" 都可能写到文档里
            trigger_v = _as_int(doc.get("trigger_count", doc.get("count", 1)), 1)
            clear_v = _as_int(doc.get("clear_time"))

            if h not in merged:
                merged[h] = {
                    "keywords": _strip_null(kw),
                    "keywords_hash": h,
                    "time": time_v,
                    "trigger_count": trigger_v,
                    "clear_time": clear_v,
                    "answers": [],
                    "bans": [],
                }
            else:
                g = merged[h]
                g["time"] = max(g["time"], time_v)
                g["trigger_count"] = max(g["trigger_count"], trigger_v)
                g["clear_time"] = max(g["clear_time"], clear_v)

            for a in _as_list(doc.get("answers")):
                if not isinstance(a, dict):
                    continue
                ak = _as_str(a.get("keywords"))
                if not ak:
                    continue
                merged[h]["answers"].append({
                    "keywords": _strip_null(ak),
                    "group_id": _as_int(a.get("group_id")),
                    "count": _as_int(a.get("count"), 1),
                    "time": _as_int(a.get("time")),
                    "messages": [_strip_null(_as_str(m)) for m in _as_list(a.get("messages")) if m is not None],
                })
            for b in _as_list(doc.get("ban")):
                if not isinstance(b, dict):
                    continue
                bk = _as_str(b.get("keywords"))
                if not bk:
                    continue
                merged[h]["bans"].append({
                    "keywords": _strip_null(bk),
                    "group_id": _as_int(b.get("group_id")),
                    "reason": _strip_null(_as_str(b.get("reason"))),
                    "time": _as_int(b.get("time")),
                })
        except Exception as e:
            stats.warn(f"context parse failed _id={doc.get('_id')}: {e}")
    return merged


def _dedupe_by_key(rows: list[dict], key_fields: tuple[str, ...]) -> list[dict]:
    """同批内按唯一键去重，后入者覆盖（Mongo 游标按 _id 升序，后者即新）。

    PG 的 INSERT ... ON CONFLICT 不允许单次语句里出现两条命中同一冲突目标的行，
    必须先在客户端侧合并。
    """
    seen: dict[tuple, dict] = {}
    for r in rows:
        k = tuple(r.get(f) for f in key_fields)
        seen[k] = r
    return list(seen.values())


def _dedupe_answers(answers: list[dict]) -> list[dict]:
    """去重 (group_id, keywords)：累加 count / 取 max time / 合并 messages。"""
    m: dict[tuple, dict] = {}
    for a in answers:
        k = (a["group_id"], a["keywords"])
        if k not in m:
            m[k] = {**a, "messages": list(a["messages"])}
        else:
            m[k]["count"] += a["count"]
            m[k]["time"] = max(m[k]["time"], a["time"])
            m[k]["messages"].extend(a["messages"])
    return list(m.values())


async def _migrate_context(db, sf, ContextRow, AnsRow, AnsMsgRow, BanRow, ins, batch_size, dry_run) -> _TableStats:
    from sqlalchemy import delete as D
    from sqlalchemy import select as S

    col = db["context"]
    stats = _TableStats()
    stats.total = await col.count_documents({})
    print(f"\n[Context] total={stats.total}")

    last_id_str: str | None = None
    if not dry_run:
        async with sf() as session:
            last_id_str = await _get_state(session, "context")
        if last_id_str:
            print(f"  [Context] resume from _id > {last_id_str}")

    t0 = time.time()
    async for batch in _stream_batches(col, last_id_str, batch_size):
        merged = _prepare_context_batch(batch, stats)
        if not merged:
            if not dry_run:
                async with sf() as session:
                    await _set_state(session, "context", str(batch[-1]["_id"]))
                    await session.commit()
            stats.skipped += len(batch)
            continue

        if not dry_run:
            async with sf() as session:
                # 1. upsert context rows
                ctx_values = [
                    {k: v for k, v in g.items() if k in ("keywords", "keywords_hash", "time", "trigger_count", "clear_time")}
                    for g in merged.values()
                ]
                stmt = ins(ContextRow).values(ctx_values)
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
                # 2. 拿回 context_id
                result = await session.execute(
                    S(ContextRow.id, ContextRow.keywords_hash).where(
                        ContextRow.keywords_hash.in_(list(merged.keys()))
                    )
                )
                h2id: dict[str, int] = {r.keywords_hash: r.id for r in result}
                ctx_ids = [cid for cid in h2id.values() if cid is not None]

                # 3. 重写 answers / bans：先删再插（针对本批涉及的 context_id）
                if ctx_ids:
                    await session.execute(D(AnsRow).where(AnsRow.context_id.in_(ctx_ids)))
                    await session.execute(D(BanRow).where(BanRow.context_id.in_(ctx_ids)))

                ans_rows: list[dict] = []
                ans_msg_pending: list[tuple[int, tuple[int, int, str], list[str]]] = []
                ban_rows: list[dict] = []

                for h, g in merged.items():
                    cid = h2id.get(h)
                    if cid is None:
                        stats.warn(f"context_id missing after upsert: hash={h}")
                        continue
                    for a in _dedupe_answers(g["answers"]):
                        kh = _kw_hash(a["keywords"])
                        ans_rows.append({
                            "context_id": cid,
                            "keywords": a["keywords"],
                            "keywords_hash": kh,
                            "group_id": a["group_id"],
                            "count": a["count"],
                            "time": a["time"],
                        })
                        if a["messages"]:
                            ans_msg_pending.append(
                                (cid, (cid, a["group_id"], kh), a["messages"])
                            )
                    for b in g["bans"]:
                        ban_rows.append({
                            "context_id": cid,
                            "keywords": b["keywords"],
                            "group_id": b["group_id"],
                            "reason": b["reason"],
                            "time": b["time"],
                        })

                # 4. 批量插 answer 并拿回 id（走 RETURNING）
                # 键 = (context_id, group_id, keywords_hash) 对齐 UNIQUE 约束，
                # 避免用 TEXT keywords 作 key 时超长字符串带来的内存开销
                key2aid: dict[tuple[int, int, str], int] = {}
                for i in range(0, len(ans_rows), _ANS_BATCH):
                    ret = await session.execute(
                        ins(AnsRow)
                        .values(ans_rows[i : i + _ANS_BATCH])
                        .returning(AnsRow.id, AnsRow.context_id, AnsRow.group_id, AnsRow.keywords_hash)
                    )
                    for r in ret.fetchall():
                        key2aid[(r.context_id, r.group_id, r.keywords_hash)] = int(r.id)

                # 5. 关联 messages
                msg_rows: list[dict] = []
                for _cid, key, messages in ans_msg_pending:
                    aid = key2aid.get(key)
                    if aid is None:
                        continue
                    msg_rows.extend({"answer_id": aid, "message": m} for m in messages)
                for i in range(0, len(msg_rows), _MSG_BATCH):
                    await session.execute(ins(AnsMsgRow).values(msg_rows[i : i + _MSG_BATCH]))

                # 6. 插 bans
                for i in range(0, len(ban_rows), _BAN_BATCH):
                    await session.execute(ins(BanRow).values(ban_rows[i : i + _BAN_BATCH]))

                # 7. 更新 migration_state 并一并 commit
                await _set_state(session, "context", str(batch[-1]["_id"]))
                await session.commit()

        stats.migrated += len(batch)
        elapsed = time.time() - t0
        rate = stats.migrated / elapsed if elapsed else 0
        eta = (stats.total - stats.migrated) / rate if rate > 0 else 0
        print(f"  [Context] {stats.migrated}/{stats.total} ({rate:.0f}/s, ETA {eta:.0f}s)", end="\r")

    print(f"  [Context] {stats.migrated}/{stats.total} done (failed={stats.failed}, skipped={stats.skipped})")
    return stats


# ---------------------------------------------------------------------------
# Message 迁移
# ---------------------------------------------------------------------------


async def _migrate_message(db, sf, MsgRow, ins, batch_size, dry_run) -> _TableStats:
    col = db["message"]
    stats = _TableStats()
    stats.total = await col.count_documents({})
    print(f"\n[Message] total={stats.total}")

    last_id_str: str | None = None
    if not dry_run:
        async with sf() as session:
            last_id_str = await _get_state(session, "message")
        if last_id_str:
            print(f"  [Message] resume from _id > {last_id_str}")

    t0 = time.time()
    async for batch in _stream_batches(col, last_id_str, max(batch_size, _MSG_ROW_BATCH)):
        rows: list[dict] = []
        for doc in batch:
            try:
                raw = _as_str(doc.get("raw_message"))
                rows.append({
                    "group_id": _as_int(doc.get("group_id")),
                    "user_id": _as_int(doc.get("user_id")),
                    "bot_id": _as_int(doc.get("bot_id")),
                    "raw_message": _strip_null(raw),
                    "is_plain_text": _as_bool(doc.get("is_plain_text"), True),
                    "plain_text": _strip_null(_as_str(doc.get("plain_text"), raw)),
                    "keywords": _strip_null(_as_str(doc.get("keywords"))),
                    "time": _as_int(doc.get("time")),
                })
            except Exception as e:
                stats.warn(f"message parse failed _id={doc.get('_id')}: {e}")

        if rows and not dry_run:
            async with sf() as session:
                # 分批插入避免超出 asyncpg 参数上限
                for i in range(0, len(rows), _MSG_ROW_BATCH):
                    await session.execute(ins(MsgRow), rows[i : i + _MSG_ROW_BATCH])
                await _set_state(session, "message", str(batch[-1]["_id"]))
                await session.commit()

        stats.migrated += len(batch)
        elapsed = time.time() - t0
        rate = stats.migrated / elapsed if elapsed else 0
        eta = (stats.total - stats.migrated) / rate if rate > 0 else 0
        print(f"  [Message] {stats.migrated}/{stats.total} ({rate:.0f}/s, ETA {eta:.0f}s)", end="\r")

    print(f"  [Message] {stats.migrated}/{stats.total} done (failed={stats.failed})")
    return stats


# ---------------------------------------------------------------------------
# BlackList / Config 系列（上游数据量小，单批搞定即可，仍走流式以防万一）
# ---------------------------------------------------------------------------


async def _migrate_blacklist(db, sf, BLRow, ins, batch_size, dry_run) -> _TableStats:
    col = db["blacklist"]
    stats = _TableStats()
    stats.total = await col.count_documents({})
    print(f"\n[BlackList] total={stats.total}")

    last_id_str: str | None = None
    if not dry_run:
        async with sf() as session:
            last_id_str = await _get_state(session, "blacklist")

    async for batch in _stream_batches(col, last_id_str, batch_size):
        rows: list[dict] = []
        for doc in batch:
            try:
                rows.append({
                    "group_id": _as_int(doc.get("group_id")),
                    "answers": [_strip_null(_as_str(x)) for x in _as_list(doc.get("answers"))],
                    "answers_reserve": [_strip_null(_as_str(x)) for x in _as_list(doc.get("answers_reserve"))],
                })
            except Exception as e:
                stats.warn(f"blacklist parse failed _id={doc.get('_id')}: {e}")

        if rows and not dry_run:
            rows = _dedupe_by_key(rows, ("group_id",))
            async with sf() as session:
                stmt = ins(BLRow).values(rows)
                await session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=["group_id"],
                        set_={"answers": stmt.excluded.answers, "answers_reserve": stmt.excluded.answers_reserve},
                    )
                )
                await _set_state(session, "blacklist", str(batch[-1]["_id"]))
                await session.commit()

        stats.migrated += len(batch)

    print(f"  [BlackList] {stats.migrated}/{stats.total} done (failed={stats.failed})")
    return stats


async def _migrate_bot_config(db, sf, BCRow, ins, batch_size, dry_run) -> _TableStats:
    col = db["config"]  # Mongo collection 名是 "config"
    stats = _TableStats()
    stats.total = await col.count_documents({})
    print(f"\n[BotConfig] total={stats.total}")

    last_id_str: str | None = None
    if not dry_run:
        async with sf() as session:
            last_id_str = await _get_state(session, "botconfig")

    async for batch in _stream_batches(col, last_id_str, batch_size):
        rows: list[dict] = []
        for raw in batch:
            try:
                # 兼容旧字段：auto_accept 仅对 group 生效
                if "auto_accept" in raw and "auto_accept_group" not in raw:
                    ag, af = _as_bool(raw.get("auto_accept")), False
                else:
                    ag = _as_bool(raw.get("auto_accept_group"))
                    af = _as_bool(raw.get("auto_accept_friend"))
                admins = []
                for x in _as_list(raw.get("admins")):
                    try:
                        admins.append(int(x))
                    except (TypeError, ValueError):
                        stats.warn(f"botconfig account={raw.get('account')} admins 非法值: {x!r}")
                tn = _as_dict(raw.get("taken_name"))
                dk = _as_dict(raw.get("drunk"))
                rows.append({
                    "account": _as_int(raw.get("account")),
                    "admins": admins,
                    "auto_accept_friend": af,
                    "auto_accept_group": ag,
                    "security": _as_bool(raw.get("security")),
                    "taken_name": {str(k): v for k, v in tn.items()},
                    "drunk": {str(k): v for k, v in dk.items()},
                    "disabled_plugins": [_strip_null(_as_str(x)) for x in _as_list(raw.get("disabled_plugins"))],
                })
            except Exception as e:
                stats.warn(f"botconfig parse failed _id={raw.get('_id')}: {e}")

        if rows and not dry_run:
            rows = _dedupe_by_key(rows, ("account",))
            async with sf() as session:
                stmt = ins(BCRow).values(rows)
                await session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=["account"],
                        set_={
                            f: getattr(stmt.excluded, f)
                            for f in (
                                "admins",
                                "auto_accept_friend",
                                "auto_accept_group",
                                "security",
                                "taken_name",
                                "drunk",
                                "disabled_plugins",
                            )
                        },
                    )
                )
                await _set_state(session, "botconfig", str(batch[-1]["_id"]))
                await session.commit()
        stats.migrated += len(batch)

    print(f"  [BotConfig] {stats.migrated}/{stats.total} done (failed={stats.failed})")
    return stats


async def _migrate_group_config(db, sf, GCRow, ins, batch_size, dry_run) -> _TableStats:
    col = db["group_config"]
    stats = _TableStats()
    stats.total = await col.count_documents({})
    print(f"\n[GroupConfig] total={stats.total}")

    last_id_str: str | None = None
    if not dry_run:
        async with sf() as session:
            last_id_str = await _get_state(session, "groupconfig")

    async for batch in _stream_batches(col, last_id_str, batch_size):
        rows: list[dict] = []
        for raw in batch:
            try:
                sing = raw.get("sing_progress")
                rows.append({
                    "group_id": _as_int(raw.get("group_id")),
                    "roulette_mode": _as_int(raw.get("roulette_mode"), 1),
                    "banned": _as_bool(raw.get("banned")),
                    "sing_progress": _strip_null(sing) if isinstance(sing, dict) else None,
                    "disabled_plugins": [_strip_null(_as_str(x)) for x in _as_list(raw.get("disabled_plugins"))],
                })
            except Exception as e:
                stats.warn(f"groupconfig parse failed _id={raw.get('_id')}: {e}")

        if rows and not dry_run:
            rows = _dedupe_by_key(rows, ("group_id",))
            async with sf() as session:
                stmt = ins(GCRow).values(rows)
                await session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=["group_id"],
                        set_={
                            f: getattr(stmt.excluded, f)
                            for f in ("roulette_mode", "banned", "sing_progress", "disabled_plugins")
                        },
                    )
                )
                await _set_state(session, "groupconfig", str(batch[-1]["_id"]))
                await session.commit()
        stats.migrated += len(batch)

    print(f"  [GroupConfig] {stats.migrated}/{stats.total} done (failed={stats.failed})")
    return stats


async def _migrate_user_config(db, sf, UCRow, ins, batch_size, dry_run) -> _TableStats:
    col = db["user_config"]
    stats = _TableStats()
    stats.total = await col.count_documents({})
    print(f"\n[UserConfig] total={stats.total}")

    last_id_str: str | None = None
    if not dry_run:
        async with sf() as session:
            last_id_str = await _get_state(session, "userconfig")

    async for batch in _stream_batches(col, last_id_str, batch_size):
        rows: list[dict] = []
        for raw in batch:
            try:
                rows.append({
                    "user_id": _as_int(raw.get("user_id")),
                    "banned": _as_bool(raw.get("banned")),
                })
            except Exception as e:
                stats.warn(f"userconfig parse failed _id={raw.get('_id')}: {e}")

        if rows and not dry_run:
            rows = _dedupe_by_key(rows, ("user_id",))
            async with sf() as session:
                stmt = ins(UCRow).values(rows)
                await session.execute(
                    stmt.on_conflict_do_update(index_elements=["user_id"], set_={"banned": stmt.excluded.banned})
                )
                await _set_state(session, "userconfig", str(batch[-1]["_id"]))
                await session.commit()
        stats.migrated += len(batch)

    print(f"  [UserConfig] {stats.migrated}/{stats.total} done (failed={stats.failed})")
    return stats


async def _migrate_image_cache(db, sf, ICRow, ins, batch_size, dry_run) -> _TableStats:
    col = db["image_cache"]
    stats = _TableStats()
    stats.total = await col.count_documents({})
    print(f"\n[ImageCache] total={stats.total}")

    last_id_str: str | None = None
    if not dry_run:
        async with sf() as session:
            last_id_str = await _get_state(session, "imagecache")

    async for batch in _stream_batches(col, last_id_str, max(batch_size, _IC_BATCH)):
        rows: list[dict] = []
        for doc in batch:
            try:
                cq = _as_str(doc.get("cq_code"))
                if not cq:
                    stats.warn(f"imagecache empty cq_code _id={doc.get('_id')}")
                    continue
                rows.append({
                    "cq_code": _strip_null(cq),
                    "base64_data": _strip_null(doc.get("base64_data")) if doc.get("base64_data") else None,
                    "ref_times": _as_int(doc.get("ref_times"), 1),
                    "date": _as_int(doc.get("date")),
                })
            except Exception as e:
                stats.warn(f"imagecache parse failed _id={doc.get('_id')}: {e}")

        if rows and not dry_run:
            rows = _dedupe_by_key(rows, ("cq_code",))
            async with sf() as session:
                for i in range(0, len(rows), _IC_BATCH):
                    stmt = ins(ICRow).values(rows[i : i + _IC_BATCH])
                    await session.execute(
                        stmt.on_conflict_do_update(
                            index_elements=["cq_code"],
                            set_={f: getattr(stmt.excluded, f) for f in ("base64_data", "ref_times", "date")},
                        )
                    )
                await _set_state(session, "imagecache", str(batch[-1]["_id"]))
                await session.commit()
        stats.migrated += len(batch)

    print(f"  [ImageCache] {stats.migrated}/{stats.total} done (failed={stats.failed})")
    return stats


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


async def migrate(
    batch_size: int,
    dry_run: bool,
    tables: set[str],
    pg_db: str | None,
    mongo_db: str | None,
    restart: bool,
) -> None:
    if pg_db:
        os.environ["PG_DB"] = pg_db
    if mongo_db:
        os.environ["MONGO_DB"] = mongo_db

    try:
        from sqlalchemy.ext.asyncio import create_async_engine
    except ImportError:
        print("❌ 缺少 SQLAlchemy/asyncpg，请执行：uv sync --extra pg")
        sys.exit(1)

    from pymongo import AsyncMongoClient
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.ext.asyncio import async_sessionmaker

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

    print(f"[Mongo] {_mongo_dsn()} db={_mongo_db_name()}")
    mongo_client = AsyncMongoClient(_mongo_dsn(), unicode_decode_error_handler="ignore")
    db = mongo_client[_mongo_db_name()]

    print(f"[PG] {_pg_dsn()}")
    if not dry_run:
        await _ensure_db()

    engine = create_async_engine(_pg_dsn(), echo=False)
    if not dry_run:
        await init_pg(engine)
        await _ensure_state_table(engine)
        if restart:
            await _reset_state(engine)

    sf = async_sessionmaker(engine, expire_on_commit=False)

    summaries: list[tuple[str, _TableStats]] = []

    if "context" in tables:
        s = await _migrate_context(
            db, sf, ContextRow, ContextAnswerRow, ContextAnswerMessageRow, ContextBanRow, pg_insert, batch_size, dry_run
        )
        summaries.append(("context", s))
    if "message" in tables:
        s = await _migrate_message(db, sf, MessageRow, pg_insert, batch_size, dry_run)
        summaries.append(("message", s))
    if "blacklist" in tables:
        s = await _migrate_blacklist(db, sf, BlackListRow, pg_insert, batch_size, dry_run)
        summaries.append(("blacklist", s))
    if "botconfig" in tables:
        s = await _migrate_bot_config(db, sf, BotConfigRow, pg_insert, batch_size, dry_run)
        summaries.append(("botconfig", s))
    if "groupconfig" in tables:
        s = await _migrate_group_config(db, sf, GroupConfigRow, pg_insert, batch_size, dry_run)
        summaries.append(("groupconfig", s))
    if "userconfig" in tables:
        s = await _migrate_user_config(db, sf, UserConfigRow, pg_insert, batch_size, dry_run)
        summaries.append(("userconfig", s))
    if "imagecache" in tables:
        s = await _migrate_image_cache(db, sf, ImageCacheRow, pg_insert, batch_size, dry_run)
        summaries.append(("imagecache", s))

    await engine.dispose()

    # 汇总
    print("\n========== 迁移摘要 ==========")
    total_failed = 0
    for name, s in summaries:
        print(f"  {name:<12} total={s.total:<10} migrated={s.migrated:<10} failed={s.failed:<6}")
        total_failed += s.failed
        for w in s.warnings[:5]:
            print(f"      · {w}")
    print(f"========== 完成（total_failed={total_failed}） ==========")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="MongoDB → PostgreSQL 数据迁移",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"可迁移的表：{', '.join(ALL_TABLES)}",
    )
    parser.add_argument("--batch", type=int, default=1000, metavar="N", help="每批处理条数（默认 1000）")
    parser.add_argument("--dry-run", action="store_true", help="只统计数量，不写入 PostgreSQL")
    parser.add_argument("--pg-db", metavar="NAME", help="目标 PG 库名，覆盖 PG_DB")
    parser.add_argument("--mongo-db", metavar="NAME", help="源 Mongo 库名，覆盖 MONGO_DB")
    parser.add_argument(
        "--tables", nargs="+", choices=ALL_TABLES, metavar="TABLE", help="仅迁移指定表（空格分隔），不指定则迁移全部"
    )
    parser.add_argument("--restart", action="store_true", help="清空 migration_state 从头迁移")
    args = parser.parse_args()

    selected = set(args.tables) if args.tables else set(ALL_TABLES)
    if args.dry_run:
        print("⚠️  dry-run 模式，不会写入 PostgreSQL")
    if args.tables:
        print(f"仅迁移：{', '.join(t for t in ALL_TABLES if t in selected)}")

    asyncio.run(migrate(args.batch, args.dry_run, selected, args.pg_db, args.mongo_db, args.restart))
