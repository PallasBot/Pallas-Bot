#!/usr/bin/env python3
"""离线 prompt lab：对 fixture 跑结构化解析 / 过滤 / 场景口气，并输出低分草稿。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def load_fixtures(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        rows.append(json.loads(text))
    return rows


def score_fixture(row: dict) -> dict:
    from pallas.core.platform.ai_callback.task_types import LLM_CHAT_TASK_TYPE
    from pallas.product.llm.kernel.models import ConversationMode, ConversationScene
    from pallas.product.llm.output_filter import resolve_output_filtered_reply
    from pallas.product.llm.reply_effect import heuristic_reply_effect_scores
    from pallas.product.llm.scene_style import format_scene_style_block, resolve_scene_style_constraints
    from pallas.product.llm.situational_rules import enrich_system_with_situational_rules
    from pallas.product.llm.structured_reply import normalize_model_reply

    user_text = str(row.get("user_text") or row.get("input") or "").strip()
    raw_reply = str(row.get("model_output") or row.get("reply") or "").strip()
    scene_raw = str(row.get("scene") or "smalltalk").strip()
    try:
        scene = ConversationScene(scene_raw)
    except ValueError:
        scene = ConversationScene.SMALLTALK

    normalized = normalize_model_reply(raw_reply)
    filtered = resolve_output_filtered_reply({"task_type": LLM_CHAT_TASK_TYPE}, normalized)
    constraints = resolve_scene_style_constraints(scene, ConversationMode.NORMAL, direct_chat=True)
    style_block = format_scene_style_block(constraints)
    system = enrich_system_with_situational_rules("你在群里闲聊。", focus_text=user_text)
    scores = heuristic_reply_effect_scores(filtered or normalized)
    low = scores.get("uncanny_risk", 3) >= 4 or not filtered
    return {
        "user_text": user_text,
        "raw_reply": raw_reply[:240],
        "normalized": normalized,
        "filtered": filtered,
        "scene": scene.value,
        "style_block": style_block,
        "system_tail": system[-240:],
        "scores": scores,
        "low_score": low,
        "draft_constraint": ("加强口语、禁止客服腔；必要时 reply=PASS。" if low else ""),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline LLM prompt lab")
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=REPO_ROOT / "tools" / "fixtures" / "llm_prompt_lab.zh.jsonl",
    )
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "llm" / "prompt_lab_out.jsonl")
    parser.add_argument("--only-low", action="store_true")
    args = parser.parse_args(argv)

    if not args.fixtures.is_file():
        print(f"fixtures not found: {args.fixtures}", file=sys.stderr)
        return 2
    rows = load_fixtures(args.fixtures)
    results = [score_fixture(row) for row in rows]
    if args.only_low:
        results = [item for item in results if item.get("low_score")]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for item in results:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"wrote {len(results)} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
