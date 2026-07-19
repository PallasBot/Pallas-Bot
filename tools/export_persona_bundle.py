"""导出 persona bundle JSON（OPT-LLM-024）。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


async def maybe_init_pg() -> None:
    from tools.integration_llm_chat import maybe_init_pg as init_pg

    await init_pg()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bot-id", type=int, default=None)
    parser.add_argument("--group-id", type=int, default=None)
    parser.add_argument("--text", default="你怎么又这样")
    parser.add_argument("--purpose", default="chat")
    parser.add_argument("--repeater-overlay", action="store_true")
    parser.add_argument("--schema-only", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--no-init-db", action="store_true")
    args = parser.parse_args()

    from pallas.product.persona.bundle_export import (
        build_persona_asset_bundle_v1,
        persona_asset_bundle_json_schema,
        serialize_persona_asset_bundle,
    )

    if args.schema_only:
        payload = persona_asset_bundle_json_schema()
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.output:
            args.output.write_text(text, encoding="utf-8")
        else:
            print(text)
        return 0

    if args.bot_id is None:
        parser.error("--bot-id is required unless --schema-only")

    async def runner() -> dict:
        from pallas.core.foundation.config.repo_settings import apply_repo_settings_to_environ

        if not args.no_init_db:
            await maybe_init_pg()
        apply_repo_settings_to_environ()
        bundle = await build_persona_asset_bundle_v1(
            int(args.bot_id),
            int(args.group_id) if args.group_id is not None else None,
            str(args.text),
            purpose=str(args.purpose),
            include_repeater_overlay=bool(args.repeater_overlay),
        )
        return serialize_persona_asset_bundle(bundle)

    payload = asyncio.run(runner())
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
