"""Run anonymous, no-delivery model quality checks."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from pallas.product.llm.offline_quality_eval import (
    ANONYMOUS_QUALITY_MATRIX,
    DEFAULT_OFFLINE_QUALITY_CASES,
    load_offline_base_system_prompt,
    run_configured_offline_quality_eval,
)
from pallas.product.llm.offline_quality_history import (
    compare_quality_baselines,
    default_quality_baseline_path,
    latest_quality_run_rows,
    read_quality_baseline_rows,
    record_quality_baseline,
    summarize_quality_baseline,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run anonymous offline LLM quality checks.")
    parser.add_argument("--system-prompt", type=Path, help="Optional static system prompt file.")
    parser.add_argument("--judge", action="store_true", help="Add an offline quality verdict for each final reply.")
    parser.add_argument(
        "--matrix",
        choices=("default", "anonymous"),
        default="default",
        help="Select the compact default set or the full anonymous matrix.",
    )
    parser.add_argument(
        "--write-baseline", action="store_true", help="Append this explicit run to the local baseline JSONL."
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    cases = ANONYMOUS_QUALITY_MATRIX if args.matrix == "anonymous" else DEFAULT_OFFLINE_QUALITY_CASES
    results = await run_configured_offline_quality_eval(
        base_system_prompt=load_offline_base_system_prompt(args.system_prompt),
        cases=cases,
        judge=args.judge,
    )
    payload: object = [asdict(result) for result in results]
    if args.write_baseline:
        matrix_version = f"{args.matrix}-v1"
        path = default_quality_baseline_path()
        previous_rows = latest_quality_run_rows(
            read_quality_baseline_rows(path=path),
            matrix_version=matrix_version,
        )
        run_id, rows, path = record_quality_baseline(
            cases,
            results,
            matrix_version=matrix_version,
            path=path,
        )
        comparison = (
            compare_quality_baselines(summarize_quality_baseline(rows), summarize_quality_baseline(previous_rows))
            if previous_rows
            else None
        )
        payload = {
            "results": payload,
            "baseline": {
                "run_id": run_id,
                "rows": len(rows),
                "path": str(path),
                "comparison": comparison,
            },
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
