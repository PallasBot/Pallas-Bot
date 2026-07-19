#!/usr/bin/env python3
"""压缩 LLM 反哺 entries：归档过旧且已 invalidate 的行，缩小全量读写成本。

用法:
  uv run python tools/compact_llm_feedback.py --dry-run
  uv run python tools/compact_llm_feedback.py --apply --keep-days 30
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def run_compact(*, apply: bool, keep_days: int, keep_eligible: bool) -> int:
    from pallas.product.llm.repeater_feedback import (
        _load_all_feedback_entries,
        _write_feedback_entries,
        feedback_base_dir,
        feedback_entries_path,
    )

    cutoff = int(time.time()) - max(1, int(keep_days)) * 86400
    entries = _load_all_feedback_entries()
    kept = []
    archived = []
    for item in entries:
        if item.eligible_for_bias and keep_eligible:
            kept.append(item)
            continue
        if int(item.created_at or 0) >= cutoff:
            kept.append(item)
            continue
        if item.eligible_for_bias:
            kept.append(item)
            continue
        archived.append(item)

    print("=== compact_llm_feedback ===")
    print(f"总行数: {len(entries)}")
    print(f"保留: {len(kept)}")
    print(f"可归档(过旧且 invalidate): {len(archived)}")
    print(f"cutoff_ts: {cutoff} keep_days={keep_days}")
    if not apply:
        print("\n(dry-run，未写入；加 --apply 执行)")
        return 0
    if not archived:
        print("\n无需写入。")
        return 0

    archive_dir = feedback_base_dir() / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    archive_path = archive_dir / f"entries_invalidated_{stamp}.jsonl"
    with archive_path.open("w", encoding="utf-8") as handle:
        for item in archived:
            handle.write(json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n")
    _write_feedback_entries(kept)
    print(f"\n已归档: {archive_path}")
    print(f"当前 entries: {feedback_entries_path()} ({len(kept)} 行)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--keep-days", type=int, default=30, help="保留最近 N 天（含已 invalidate）")
    parser.add_argument(
        "--drop-old-eligible",
        action="store_true",
        help="同时归档过旧但仍 eligible 的行（默认只归档 invalidate）",
    )
    args = parser.parse_args()
    return run_compact(
        apply=args.apply,
        keep_days=max(1, int(args.keep_days)),
        keep_eligible=not args.drop_old_eligible,
    )


if __name__ == "__main__":
    raise SystemExit(main())
