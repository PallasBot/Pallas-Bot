#!/usr/bin/env python3
"""扫描并清理复读语料中的污染回复（PostgreSQL / MongoDB）。

用法:
  uv run python tools/clean_pg_corpus.py --dry-run
  uv run python tools/clean_pg_corpus.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


async def run_cleanup(*, apply: bool, preview_limit: int) -> int:
    from pallas.core.foundation.config.repo_settings import apply_repo_settings_to_environ
    from pallas.core.foundation.db import get_db_backend, is_mongodb_backend, is_postgresql_backend
    from pallas.product.llm.corpus_contamination import run_corpus_contamination_cleanup

    apply_repo_settings_to_environ()
    backend = get_db_backend()
    if not is_postgresql_backend() and not is_mongodb_backend():
        print(f"当前 DB_BACKEND={backend!r} 不支持语料扫库（仅 postgresql / mongodb）")
        return 1

    report = await run_corpus_contamination_cleanup(apply=apply, preview_limit=preview_limit)

    print(f"=== clean_corpus ({backend}) ===")
    print(f"复读语料 message 待删: {report.answer_message_candidates}")
    print(f"空 answer 待删: {report.parent_answer_candidates}")
    print(f"message 历史待删: {report.message_candidates}")
    print()
    if not apply:
        print("\n(dry-run，未写入；加 --apply 执行)")
        return 0
    if not report.deleted_answer_messages and not report.deleted_message_history:
        print("\n无需写入。")
        return 0
    print()
    print(f"已删除复读语料 message: {report.deleted_answer_messages}")
    print(f"已删除空 answer: {report.deleted_empty_answers}")
    print(f"已删除 message 历史: {report.deleted_message_history}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="只统计与预览，不写盘")
    mode.add_argument("--apply", action="store_true", help="执行清理并写盘")
    parser.add_argument("--preview", type=int, default=20, help="预览条数")
    args = parser.parse_args()
    return asyncio.run(run_cleanup(apply=args.apply, preview_limit=max(0, int(args.preview))))


if __name__ == "__main__":
    raise SystemExit(main())
