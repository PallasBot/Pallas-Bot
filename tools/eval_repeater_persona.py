"""抽样检查 repeater LLM 塑形块是否写入 system prompt。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PURPOSES = ("polish_lite", "select", "fallback_lite", "polish")
DEFAULT_SAMPLE_TEXTS = (
    "你怎么又这样",
    "这次抽卡也太黑了吧",
    "在吗",
    "哈哈哈笑死",
)


async def maybe_init_pg() -> None:
    from tools.integration_llm_chat import maybe_init_pg as init_pg

    await init_pg()


async def discover_sample_targets(*, limit: int = 3) -> list[tuple[int, int]]:
    from sqlalchemy import text

    from pallas.core.foundation.db.repository_pg import get_session

    async with get_session(read_only=True) as session:
        group_rows = await session.execute(
            text("SELECT group_id FROM group_config ORDER BY group_id DESC LIMIT :limit"),
            {"limit": max(1, int(limit))},
        )
        group_ids = [int(row[0]) for row in group_rows.fetchall()]
        bot_rows = await session.execute(
            text("SELECT account FROM bot_config ORDER BY account LIMIT :limit"),
            {"limit": max(1, int(limit))},
        )
        bot_ids = [int(row[0]) for row in bot_rows.fetchall()]
    if not group_ids or not bot_ids:
        return [(1, 10001)]
    return [(bot_ids[0], group_ids[0])]


async def run_persona_check(
    *,
    group_id: int,
    bot_id: int,
    user_text: str,
) -> dict[str, object]:
    from pallas.core.foundation.config.repo_settings import apply_repo_settings_to_environ
    from pallas.product.llm.repeater_persona_context import build_repeater_llm_persona_context

    apply_repo_settings_to_environ()
    results: dict[str, object] = {}
    for purpose in PURPOSES:
        bundle = await build_repeater_llm_persona_context(
            bot_id,
            group_id,
            user_text,
            purpose=purpose,
            user_id=1,
        )
        if bundle is None:
            results[purpose] = {"ok": False, "reason": "empty_bundle"}
            continue
        prompt = bundle.system_prompt
        results[purpose] = {
            "ok": "【接话塑形】" in prompt,
            "has_dynamic": bool(bundle.dynamic_expression_hint),
            "has_variation": bool(bundle.variation_hint),
            "rewrite_active": bool(bundle.llm_rewrite_metadata.get("persona_shaping_active")),
            "preserve_colloquial": bool(bundle.llm_rewrite_metadata.get("preserve_colloquial_rewrite")),
            "prompt_chars": len(prompt),
        }
    return results


async def run_batch_eval(
    *,
    group_id: int | None,
    bot_id: int | None,
    texts: list[str],
    auto_discover: bool,
) -> dict[str, object]:
    if auto_discover or group_id is None or bot_id is None:
        targets = await discover_sample_targets()
        resolved_bot_id, resolved_group_id = targets[0]
    else:
        resolved_bot_id, resolved_group_id = int(bot_id), int(group_id)

    samples: dict[str, object] = {}
    for text in texts:
        samples[text] = await run_persona_check(
            group_id=resolved_group_id,
            bot_id=resolved_bot_id,
            user_text=text,
        )
    failed_purposes = {
        text: [purpose for purpose, row in (result or {}).items() if not isinstance(row, dict) or not row.get("ok")]
        for text, result in samples.items()
    }
    dynamic_checks = 0
    dynamic_hits = 0
    for result in samples.values():
        if not isinstance(result, dict):
            continue
        for row in result.values():
            if not isinstance(row, dict):
                continue
            dynamic_checks += 1
            if row.get("has_dynamic"):
                dynamic_hits += 1
    dynamic_hit_rate = round(dynamic_hits / dynamic_checks, 3) if dynamic_checks else 0.0
    dynamic_warn = dynamic_checks > 0 and dynamic_hit_rate < 0.25
    return {
        "bot_id": resolved_bot_id,
        "group_id": resolved_group_id,
        "samples": samples,
        "failed": failed_purposes,
        "all_ok": not any(failed_purposes.values()),
        "dynamic_hit_rate": dynamic_hit_rate,
        "dynamic_warn": dynamic_warn,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group-id", type=int, default=None)
    parser.add_argument("--bot-id", type=int, default=None)
    parser.add_argument("--text", action="append", dest="texts", default=[])
    parser.add_argument("--no-init-db", action="store_true")
    parser.add_argument("--auto-discover", action="store_true", help="从 PG 自动选取 bot/group")
    args = parser.parse_args()
    texts = list(args.texts) or list(DEFAULT_SAMPLE_TEXTS)

    async def runner() -> dict[str, object]:
        if not args.no_init_db:
            await maybe_init_pg()
        return await run_batch_eval(
            group_id=args.group_id,
            bot_id=args.bot_id,
            texts=texts,
            auto_discover=bool(args.auto_discover or args.group_id is None or args.bot_id is None),
        )

    report = asyncio.run(runner())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get("dynamic_warn"):
        print(
            f"WARN: dynamic_expression 命中率偏低 ({report.get('dynamic_hit_rate')})，"
            "可检查群近场语料或 style_profile。",
            file=sys.stderr,
        )
    return 0 if report.get("all_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
