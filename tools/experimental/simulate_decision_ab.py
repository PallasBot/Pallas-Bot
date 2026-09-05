#!/usr/bin/env python3
"""用真实语料模拟开启 current_turn_decision 后的决策差异（rule vs model）。

数据源：data/pb_webui/repeater_semantic_style/examples.jsonl 的真人 trigger。
对比：纯规则 decide_current_turn_by_rule vs 模型 decide_current_turn(model_enabled=True)。
输出：差异统计 + 样本行，落 data/llm/decision_ab_out.jsonl。

用法：uv run python tools/simulate_decision_ab.py --limit 80 --out data/llm/decision_ab_<ts>.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pallas.product.llm.current_turn_decision import (
    CurrentTurnAction,
    CurrentTurnDecisionInput,
    build_current_turn_decision_prompt,
    decide_current_turn_by_rule,
    decide_current_turn,
)
from pallas.product.llm.provider_client import complete_chat_message
from pallas.product.llm.providers_store import find_provider, resolve_provider_api_keys

DEFAULT_SOURCE = REPO_ROOT / "data" / "pb_webui" / "repeater_semantic_style" / "examples.jsonl"
DEFAULT_PROVIDER = "ds"
DEFAULT_MODEL = "deepseek-v4-flash"


def load_triggers(path: Path, limit: int | None, seed: int) -> list[str]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            trigger = str(obj.get("trigger_text") or "").strip()
            if not trigger or "[CQ:" in trigger:
                continue
            rows.append(trigger)
    rng = random.Random(seed)
    rng.shuffle(rows)
    return rows[:limit] if limit else rows


async def classify(
    provider_id: str, model: str, turn: CurrentTurnDecisionInput
) -> str:
    prompt = build_current_turn_decision_prompt(turn)
    row = find_provider(provider_id, include_disabled=True)
    keys = resolve_provider_api_keys(row) if row else []
    if not row or not keys:
        raise SystemExit(f"provider [{provider_id}] unavailable")
    base_url = row["base_url"]
    api_key = keys[0]
    resp = await complete_chat_message(
        [
            {"role": "system", "content": "You classify chat turns. Reply with JSON only."},
            {"role": "user", "content": prompt},
        ],
        model=model,
        options={"temperature": 0.0, "max_tokens": 120},
        base_url=base_url,
        api_key=api_key,
        task="turn_decision",
        provider_id=provider_id,
    )
    return str(resp.get("content") or "").strip()


async def main() -> int:
    parser = argparse.ArgumentParser(description="Simulate decision rule vs model on real triggers")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "llm" / "decision_ab_out.jsonl")
    args = parser.parse_args()

    triggers = load_triggers(args.source, args.limit, args.seed)
    print(f"loaded {len(triggers)} triggers from {args.source}", flush=True)

    results = []
    for idx, text in enumerate(triggers):
        turn = CurrentTurnDecisionInput(text=text)
        rule_dec = decide_current_turn_by_rule(turn)
        raw = await classify(args.provider, args.model, turn)
        model_dec = decide_current_turn(
            turn, model_enabled=True, model_response=raw
        )
        row = {
            "idx": idx,
            "text": text,
            "rule": {"action": rule_dec.action.value, "reason": rule_dec.trace.reason},
            "model": {
                "action": model_dec.action.value,
                "social_action": model_dec.social_action.value,
                "source": model_dec.trace.source,
                "reason": model_dec.trace.reason,
            },
        }
        results.append(row)
        flag = "" if row["rule"]["action"] == row["model"]["action"] else "  <== DIFF"
        print(
            f"[{idx}] rule={row['rule']['action']:<6} model={row['model']['action']:<6} "
            f"src={row['model']['source']:<8} | {text[:30]}{flag}",
            flush=True,
        )

    from collections import Counter

    rule_actions = Counter(r["rule"]["action"] for r in results)
    model_actions = Counter(r["model"]["action"] for r in results)
    print("\n== rule action distribution:", dict(rule_actions))
    print("== model action distribution:", dict(model_actions))

    diff = [r for r in results if r["rule"]["action"] != r["model"]["action"]]
    print(f"== diffs: {len(diff)}/{len(results)}")
    pass_kept = sum(1 for r in results if r["rule"]["action"] == "PASS" and r["model"]["action"] == "PASS")
    pass_to_reply = sum(1 for r in results if r["rule"]["action"] == "PASS" and r["model"]["action"] == "REPLY")
    pass_to_tool = sum(1 for r in results if r["rule"]["action"] == "PASS" and r["model"]["action"] == "TOOL")
    reply_to_pass = sum(1 for r in results if r["rule"]["action"] == "REPLY" and r["model"]["action"] == "PASS")
    print(f"   PASS kept {pass_kept}, PASS->REPLY {pass_to_reply}, PASS->TOOL {pass_to_tool}, REPLY->PASS {reply_to_pass}")

    for item in diff:
        print(f"   {item['rule']['action']}->{item['model']['action']} | {item['text'][:40]}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as handle:
            for item in results:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"wrote {len(results)} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))