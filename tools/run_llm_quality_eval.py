"""Run anonymous, no-delivery model quality checks."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from pallas.product.llm.offline_quality_eval import (
    load_offline_base_system_prompt,
    run_configured_offline_quality_eval,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run anonymous offline LLM quality checks.")
    parser.add_argument("--system-prompt", type=Path, help="Optional static system prompt file.")
    parser.add_argument("--judge", action="store_true", help="Add an offline quality verdict for each final reply.")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    results = await run_configured_offline_quality_eval(
        base_system_prompt=load_offline_base_system_prompt(args.system_prompt),
        judge=args.judge,
    )
    print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
