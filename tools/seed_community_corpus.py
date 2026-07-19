#!/usr/bin/env python3
"""
从本地 PostgreSQL repeater 语料挑选一部分，上传到社区中心 /v1/corpus/contribute。

用法（在 Pallas-Bot 仓库根目录，已配置 config/pallas.toml 与 PG）：

    uv run python tools/seed_community_corpus.py --dry-run
    uv run python tools/seed_community_corpus.py --limit 2000 --min-answer-count 3

选项：
    --limit N              最多上传 N 条 answer（默认 2000）
    --min-answer-count N   本地 answer.count 下限（默认 3）
    --min-trigger N        context.trigger_count 下限（默认 2）
    --dry-run              只统计，不 POST
    --enroll-url URL       默认 https://stats.pallasbot.top/v1/corpus/enroll
    --token TOKEN          跳过 enroll，直接用已有 pc_ token

环境：读取 pallas.toml / .env 的 PG_*；可用 PALLAS_CORPUS_COMMUNITY_API_BASE 覆盖读端校验。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


async def main() -> int:
    parser = argparse.ArgumentParser(description="Seed community corpus from local PG")
    parser.add_argument("--limit", type=int, default=2000)
    parser.add_argument("--min-answer-count", type=int, default=3)
    parser.add_argument("--min-trigger", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--enroll-url",
        default=os.getenv(
            "PALLAS_CORPUS_SEED_ENROLL_URL",
            "https://stats.pallasbot.top/v1/corpus/enroll",
        ),
    )
    parser.add_argument("--token", default=os.getenv("PALLAS_CORPUS_TOKEN", ""))
    args = parser.parse_args()

    from sqlalchemy import select

    from pallas.core.foundation.config.repo_settings import apply_repo_settings_to_environ
    from pallas.core.foundation.db import init_postgresql_db
    from pallas.core.foundation.db.repository_pg import _LOAD_RELATED, ContextRow, dispose_pg, get_session, row_to_context

    apply_repo_settings_to_environ()
    await init_postgresql_db()

    api_base = ""
    token = (args.token or "").strip()
    if not token and not args.dry_run:
        dep = str(uuid.uuid4())
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(args.enroll_url, json={"deployment_id": dep})
            resp.raise_for_status()
            data = resp.json()
            token = str(data.get("corpus_token") or "")
            api_base = str(data.get("api_base") or "").rstrip("/")
        if not token:
            print("enroll 未返回 corpus_token", file=sys.stderr)
            return 1
        print(f"enrolled deployment_id={dep} api_base={api_base}")
    elif token:
        manual_base = (os.getenv("PALLAS_CORPUS_COMMUNITY_API_BASE") or "").strip().rstrip("/")
        api_base = manual_base or args.enroll_url.replace("/corpus/enroll", "/corpus").rstrip("/")

    contribute_url = f"{api_base}/contribute" if api_base else ""
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    uploaded = 0
    scanned = 0
    last_id = 0
    batch = 100

    try:
        while uploaded < args.limit:
            async with get_session() as session:
                result = await session.execute(
                    select(ContextRow)
                    .options(*_LOAD_RELATED)
                    .where(ContextRow.id > last_id, ContextRow.trigger_count >= args.min_trigger)
                    .order_by(ContextRow.trigger_count.desc(), ContextRow.id)
                    .limit(batch)
                )
                rows = list(result.scalars().all())
            if not rows:
                break
            last_id = rows[-1].id

            async with httpx.AsyncClient(timeout=30.0) as client:
                for row in rows:
                    ctx = row_to_context(row)
                    if not ctx or not ctx.keywords.strip():
                        continue
                    best_by_answer: dict[str, tuple[int, int, str]] = {}
                    for ans in ctx.answers:
                        scanned += 1
                        if ans.count < args.min_answer_count:
                            continue
                        ak = (ans.keywords or "").strip()
                        if not ak:
                            continue
                        msg = (ans.messages[0] if ans.messages else ak).strip()
                        if not msg:
                            continue
                        prev = best_by_answer.get(ak)
                        if prev is None or ans.count > prev[0]:
                            best_by_answer[ak] = (ans.count, ans.time, msg)

                    for answer_keywords, (_count, answer_time, message) in best_by_answer.items():
                        if uploaded >= args.limit:
                            break
                        payload = {
                            "op": "upsert_answer",
                            "keywords": ctx.keywords.strip(),
                            "group_id": 0,
                            "answer_keywords": answer_keywords,
                            "answer_time": answer_time,
                            "message": message[:500],
                            "append_on_existing": True,
                        }
                        if args.dry_run:
                            uploaded += 1
                            continue
                        resp = await client.post(contribute_url, json=payload, headers=headers)
                        if resp.status_code >= 400:
                            print(
                                f"contribute failed {resp.status_code} kw={ctx.keywords[:40]!r}: {resp.text[:120]}",
                                file=sys.stderr,
                            )
                            continue
                        uploaded += 1
                        if uploaded % 200 == 0:
                            print(f"uploaded {uploaded}...")
    finally:
        await dispose_pg()

    mode = "would upload" if args.dry_run else "uploaded"
    print(f"{mode} {uploaded} answers (scanned {scanned} local answer rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
