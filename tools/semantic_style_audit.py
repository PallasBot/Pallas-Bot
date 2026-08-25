#!/usr/bin/env python3
"""离线审计语义风格指导器产出：不调 LLM，纯用现有 profiles.json 数据验证产出合理性。

三种自一致性检查 + 一种触发句驱动召回检查：
1. 节奏基线：样本足够时 build_rhythm_baseline_note 是否产出合理一句话
2. 匹配对召回：拿 profile 里真实 trigger 去 select_semantic_style_matched_pairs，
   看能否召回到同 profile 的「正确处理」，而不是无关对或空
3. 行为策略召回：select_behavior_strategies 按 query_text 召回的策略是否针对性够
4. 相似度健康度：profile 内 direct_pairs 两两相似度分布，判断参考样本是否足够多样

数据源：data/pb_webui/repeater_semantic_style/profiles.json
输出：结构化的每群汇总 + 整体统计，落 data/llm/semantic_style_audit.json（可选 stdout）。

用法：
    uv run python tools/semantic_style_audit.py [--min-sample 8] [--out data/llm/semantic_style_audit.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from operator import itemgetter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pallas.product.llm.repeater_semantic_style import (  # noqa: E402
    SemanticStyleDirectPair,
    SemanticStyleProfile,
    build_rhythm_baseline_note,
    select_semantic_style_matched_pairs,
    semantic_style_text_similarity,
)


def load_profiles() -> list[SemanticStyleProfile]:
    path = REPO_ROOT / "data" / "pb_webui" / "repeater_semantic_style" / "profiles.json"
    if not path.exists():
        raise SystemExit(f"profiles.json not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("profiles") if isinstance(raw, dict) else raw
    items: list[SemanticStyleProfile] = []
    for item in rows or []:
        try:
            items.append(SemanticStyleProfile.model_validate(item))
        except Exception:
            continue
    return items


def audit_profile(profile: SemanticStyleProfile) -> dict[str, object]:
    entries: dict[str, object] = {
        "profile_ref": f"{profile.bot_id}:{profile.group_id}:{profile.scene}",
        "scene": profile.scene,
        "sample_count": profile.sample_count,
    }

    baseline = build_rhythm_baseline_note(profile)
    entries["rhythm_baseline"] = baseline

    pairs = profile.direct_pairs
    entries["direct_pair_count"] = len(pairs)

    if pairs:
        similarities: list[float] = []
        for index, left in enumerate(pairs):
            similarities.extend(
                semantic_style_text_similarity(left.reply_text, right.reply_text) for right in pairs[index + 1 :]
            )
        if similarities:
            avg_sim = sum(similarities) / len(similarities)
            entries["reply_pair_avg_similarity"] = round(avg_sim, 3)
            max_sim = max(similarities)
            entries["reply_pair_max_similarity"] = round(max_sim, 3)
        else:
            entries["reply_pair_avg_similarity"] = None

        recent: list[str] = []
        hits: list[SemanticStyleDirectPair] = []
        for query in [pair.trigger_text for pair in pairs]:
            if not query:
                continue
            matched = select_semantic_style_matched_pairs(
                list(pairs),
                query_text=query,
                recent_assistant_replies=recent,
            )
            if matched:
                hits.append(matched[0])
                recent.append(matched[0].reply_text)
        entries["matched_hit_count"] = len(hits)
        entries["matched_hit_rate"] = round(len(hits) / max(1, len(pairs)), 3) if pairs else None

    strategies = profile.behavior_strategies
    entries["behavior_strategy_count"] = len(strategies)
    entries["strategy_hit_rate"] = None
    if strategies:
        trigger_seqs = [pair.trigger_text for pair in pairs if pair.trigger_text]
        pairs_len = len(trigger_seqs)
        total = pairs_len * len(strategies)
        hits = 0
        for query in trigger_seqs:
            for strategy in strategies:
                if (
                    max(
                        semantic_style_text_similarity(query, strategy.trigger),
                        semantic_style_text_similarity(query, strategy.scene),
                    )
                    >= 0.3
                ):
                    hits += 1
        entries["strategy_hit_rate"] = round(hits / total, 3) if total else None
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description="审计语义风格指导器离线产出质量。")
    parser.add_argument("--min-sample", type=int, default=8, help="只审计样本数 ≥ 该值的 profile")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "llm" / "semantic_style_audit.json")
    parser.add_argument(
        "--json",
        action="store_true",
        help="直接输出 JSON（供上游消费），否则打印人类可读汇总",
    )
    args = parser.parse_args()

    profiles = load_profiles()
    profiles = [profile for profile in profiles if profile.sample_count >= args.min_sample]
    print(f"profiles 总数 {len(load_profiles())}，>= min-sample({args.min_sample}) {len(profiles)} 个")

    audited = [audit_profile(profile) for profile in profiles]

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(
                {
                    "generated_at": None,
                    "min_sample": args.min_sample,
                    "profiles": audited,
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        print(f"已写入 {args.out}")

    if args.json:
        print(json.dumps({"profiles": audited}, ensure_ascii=False))
        return

    overall = len(audited)
    with_ref = [item for item in audited if item["direct_pair_count"]]
    with_baseline = [item for item in audited if item["rhythm_baseline"]]
    print("=" * 60)
    print("语义风格产出审计汇总")
    print("=" * 60)
    print(f"有 direct_pairs 的群：{len(with_ref)} / {overall}")
    print(f"有节奏基线的群：{len(with_baseline)} / {overall}")
    if with_ref:
        hit_rates = [item["matched_hit_rate"] for item in with_ref if item["matched_hit_rate"] is not None]
        avg_hit = sum(hit_rates) / len(hit_rates) if hit_rates else 0
        print(f"匹配对召回率（自触发→自命中）：平均 {avg_hit:.3f}（{len(hit_rates)} 群参与）")
    print()
    for item in sorted(with_ref, key=itemgetter("direct_pair_count"), reverse=True)[:8]:
        print(
            f"[{item['profile_ref']}] 样本{item['sample_count']} 对{item['direct_pair_count']} "
            f"基线:{item['rhythm_baseline'] or '无'}"
        )
        print(
            f"   召回率 {item['matched_hit_rate']} 策略数 {item['behavior_strategy_count']} "
            f"策略命中率 {item['strategy_hit_rate']} 平均相似度 {item['reply_pair_avg_similarity']}"
        )


if __name__ == "__main__":
    main()
