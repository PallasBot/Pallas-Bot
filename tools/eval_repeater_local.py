"""分析本地接话/LLM 持久化数据，导出可 replay 用例与输出过滤词表草案。"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from pallas.product.llm.output_filter import (
    CHAT_HARD_BLOCK_PHRASES,
    CHAT_SOFT_RETRY_PHRASES,
    POLISH_LITE_HARD_BLOCK_PHRASES,
    POLISH_LITE_SOFT_RETRY_PHRASES,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data" / "pb_webui"


def default_data_dir() -> Path:
    return DEFAULT_DATA


def feedback_entries_path_for(data_dir: Path | None) -> Path:
    base = data_dir or default_data_dir()
    return base / "llm_repeater_feedback" / "entries.jsonl"


def opportunity_trace_path(data_dir: Path | None = None) -> Path:
    base = data_dir or default_data_dir()
    return base / "repeater_opportunity_trace.jsonl"


def metrics_history_path(data_dir: Path | None = None) -> Path:
    base = data_dir or default_data_dir()
    return base / "repeater_metrics_history.jsonl"


def iter_jsonl(path: Path):
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def analyze_feedback(path: Path) -> dict[str, object]:
    routes: Counter[str] = Counter()
    scenes: Counter[str] = Counter()
    total = 0
    for row in iter_jsonl(path):
        total += 1
        routes[str(row.get("llm_route") or "")] += 1
        scenes[str(row.get("behavior_scene") or "")] += 1
    return {
        "path": str(path),
        "total": total,
        "routes": dict(routes.most_common(12)),
        "scenes": dict(scenes.most_common(12)),
        "note": "主要来自 @闲聊 短回复；接话 corpus_* 路由占比较小，可用于 polish/select 回归。",
    }


def analyze_opportunity(path: Path) -> dict[str, object]:
    kinds: Counter[str] = Counter()
    actions: Counter[str] = Counter()
    stages: Counter[str] = Counter()
    accepted = 0
    rejected = 0
    for row in iter_jsonl(path):
        kinds[str(row.get("kind") or "")] += 1
        if row.get("kind") != "conversation_decision_trace":
            continue
        actions[str(row.get("action") or "")] += 1
        if row.get("opportunity_accepted"):
            accepted += 1
        else:
            rejected += 1
        for stage in row.get("generation_stages") or []:
            stages[str(stage)] += 1
    return {
        "path": str(path),
        "kinds": dict(kinds.most_common(8)),
        "actions": dict(actions.most_common(10)),
        "accepted": accepted,
        "rejected": rejected,
        "stages": dict(stages.most_common(10)),
        "note": "decision_trace 含 opportunity_gate 与 generation_stages，适合导出 replay 用例。",
    }


def export_replay_cases(
    path: Path,
    *,
    limit: int,
    action: str,
    only_accepted: bool,
) -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []
    want_action = (action or "").strip()
    for row in iter_jsonl(path):
        if row.get("kind") != "conversation_decision_trace":
            continue
        if only_accepted and not row.get("opportunity_accepted"):
            continue
        row_action = str(row.get("action") or "")
        if want_action and row_action != want_action:
            continue
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        stages = list(row.get("generation_stages") or [])
        scenario = "fallback"
        if "select" in stages:
            scenario = "select"
        elif row_action in {"reply_rewrite", "reply_generate"}:
            scenario = "polish"
        cases.append({
            "group_id": row.get("group_id"),
            "bot_id": row.get("bot_id"),
            "action": row_action,
            "scenario": scenario,
            "trace_reason": row.get("trace_reason"),
            "generation_stages": stages,
            "plain_preview": extra.get("plain_preview") or extra.get("plain_len"),
            "candidate_pool_size": extra.get("candidate_pool_size"),
            "reply_mode": extra.get("reply_mode") or row.get("mode"),
            "opportunity_accepted": bool(row.get("opportunity_accepted")),
        })
        if len(cases) >= max(1, limit):
            break
    return cases


_SERVICE_TONE_MARKERS = ("博士", "您", "请问", "有什么可以", "聊聊吗", "嘻嘻", "[嘻嘻]")

_CHAT_FILTER_SEEDS = CHAT_HARD_BLOCK_PHRASES + CHAT_SOFT_RETRY_PHRASES + (
    "请问",
    "为您服务",
    "随时为你",
    "随时为您",
    "还有其他",
)

_POLISH_FILTER_SEEDS = POLISH_LITE_HARD_BLOCK_PHRASES + POLISH_LITE_SOFT_RETRY_PHRASES + (
    "因为",
    "通常",
    "一般来说",
    "总结一下",
    "首先",
    "要不咱",
    "不妨",
)

_FEEDBACK_GATE_HINTS = _POLISH_FILTER_SEEDS[:5]

_CHAT_HARD_MIN_COUNT = 8
_CHAT_SOFT_MIN_COUNT = 3
_POLISH_HARD_MIN_COUNT = 5
_POLISH_SOFT_MIN_COUNT = 2
_POLISH_LONG_REPLY_LEN = 22


def _phrase_hits(text: str, phrases: tuple[str, ...]) -> list[str]:
    return [phrase for phrase in phrases if phrase and phrase in text]


def _collect_phrase_evidence(
    entries: list[dict[str, object]],
    *,
    phrases: tuple[str, ...],
    route_prefix: str | None = None,
) -> dict[str, dict[str, object]]:
    evidence: dict[str, dict[str, object]] = {}
    for phrase in phrases:
        count = 0
        route_counts: Counter[str] = Counter()
        samples: list[dict[str, str]] = []
        for row in entries:
            route = str(row.get("llm_route") or "")
            if route_prefix and not route.startswith(route_prefix):
                continue
            reply = str(row.get("reply_text") or "").strip()
            if phrase not in reply:
                continue
            count += 1
            route_counts[route] += 1
            if len(samples) < 3:
                samples.append({
                    "user": str(row.get("user_text") or "")[:48],
                    "reply": reply[:72],
                    "route": route,
                })
        if count:
            evidence[phrase] = {
                "count": count,
                "routes": dict(route_counts.most_common(6)),
                "samples": samples,
            }
    return evidence


def build_output_filter_draft(path: Path) -> dict[str, object]:
    entries = list(iter_jsonl(path))
    plain_entries = [row for row in entries if str(row.get("llm_route") or "") == "plain_llm_chat"]
    polish_entries = [row for row in entries if str(row.get("llm_route") or "") == "corpus_polish_lite"]

    chat_evidence = _collect_phrase_evidence(plain_entries, phrases=_CHAT_FILTER_SEEDS)
    polish_evidence = _collect_phrase_evidence(polish_entries, phrases=_POLISH_FILTER_SEEDS)

    chat_hard: list[str] = []
    chat_soft: list[str] = []
    chat_observe: list[str] = []
    for phrase, meta in sorted(chat_evidence.items(), key=lambda item: -int(item[1]["count"])):  # type: ignore[arg-type]
        count = int(meta["count"])
        if count >= _CHAT_HARD_MIN_COUNT:
            chat_hard.append(phrase)
        elif count >= _CHAT_SOFT_MIN_COUNT:
            chat_soft.append(phrase)
        else:
            chat_observe.append(phrase)

    polish_hard: list[str] = []
    polish_soft: list[str] = []
    polish_observe: list[str] = []
    for phrase, meta in sorted(polish_evidence.items(), key=lambda item: -int(item[1]["count"])):  # type: ignore[arg-type]
        count = int(meta["count"])
        if count >= _POLISH_HARD_MIN_COUNT:
            polish_hard.append(phrase)
        elif count >= _POLISH_SOFT_MIN_COUNT:
            polish_soft.append(phrase)
        else:
            polish_observe.append(phrase)

    long_polish_samples: list[dict[str, str]] = []
    for row in polish_entries:
        reply = str(row.get("reply_text") or "").strip()
        if len(reply) < _POLISH_LONG_REPLY_LEN:
            continue
        if not _phrase_hits(reply, _POLISH_FILTER_SEEDS):
            continue
        if len(long_polish_samples) >= 8:
            break
        long_polish_samples.append({
            "user": str(row.get("user_text") or "")[:48],
            "reply": reply[:96],
            "route": "corpus_polish_lite",
        })

    service_tone = sum(
        1
        for row in plain_entries
        if any(marker in str(row.get("reply_text") or "") for marker in _SERVICE_TONE_MARKERS)
    )
    plain_total = len(plain_entries) or 1

    return {
        "version": "draft-review-1",
        "generated_at": int(time.time()),
        "source": {
            "feedback_path": str(path),
            "total_entries": len(entries),
            "plain_llm_chat_entries": len(plain_entries),
            "corpus_polish_lite_entries": len(polish_entries),
            "plain_service_tone_rate": round(service_tone / plain_total, 4),
        },
        "review_policy": (
            "草案用于评审与 export；运行时词表见 pallas/product/llm/output_filter.py。"
            "上线后 hard/soft 均在 callback 投递前拦截；接话任务优先回落语料 fallback。"
        ),
        "tiers": {
            "chat_hard_block": chat_hard,
            "chat_soft_retry": chat_soft,
            "polish_lite_hard_block": polish_hard,
            "polish_lite_soft_retry": polish_soft,
            "observe_only": sorted(set(chat_observe + polish_observe)),
        },
        "evidence": {
            "chat": {
                phrase: chat_evidence[phrase]
                for phrase in chat_hard + chat_soft + chat_observe
                if phrase in chat_evidence
            },
            "polish_lite": {
                phrase: polish_evidence[phrase]
                for phrase in polish_hard + polish_soft + polish_observe
                if phrase in polish_evidence
            },
            "polish_lite_long_reply_samples": long_polish_samples,
        },
        "already_in_prompt": list(CHAT_HARD_BLOCK_PHRASES + CHAT_SOFT_RETRY_PHRASES),
        "already_in_runtime_filter": {
            "chat_hard_block": list(CHAT_HARD_BLOCK_PHRASES),
            "chat_soft_retry": list(CHAT_SOFT_RETRY_PHRASES),
            "polish_lite_hard_block": list(POLISH_LITE_HARD_BLOCK_PHRASES),
            "polish_lite_soft_retry": list(POLISH_LITE_SOFT_RETRY_PHRASES),
        },
        "already_in_feedback_gate": list(_FEEDBACK_GATE_HINTS),
        "thresholds": {
            "chat_hard_min_count": _CHAT_HARD_MIN_COUNT,
            "chat_soft_min_count": _CHAT_SOFT_MIN_COUNT,
            "polish_hard_min_count": _POLISH_HARD_MIN_COUNT,
            "polish_soft_min_count": _POLISH_SOFT_MIN_COUNT,
        },
    }


def cmd_export_filter_draft(data_dir: Path | None, *, out: Path) -> int:
    fb_path = feedback_entries_path_for(data_dir)
    if not fb_path.is_file():
        print(json.dumps({"error": f"feedback not found: {fb_path}"}, ensure_ascii=False))
        return 1
    draft = build_output_filter_draft(fb_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        json.dump(draft, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"exported filter draft -> {out}")
    print(
        json.dumps(
            {
                "chat_hard_block": len(draft["tiers"]["chat_hard_block"]),  # type: ignore[index]
                "chat_soft_retry": len(draft["tiers"]["chat_soft_retry"]),  # type: ignore[index]
                "polish_lite_hard_block": len(draft["tiers"]["polish_lite_hard_block"]),  # type: ignore[index]
            },
            ensure_ascii=False,
        )
    )
    return 0


def evaluate_feedback_quality(path: Path) -> dict[str, object]:
    routes: Counter[str] = Counter()
    scenes: Counter[str] = Counter()
    reply_lengths: list[int] = []
    service_tone = 0
    top_replies_by_route: dict[str, Counter[str]] = {}
    samples_service: list[dict[str, str]] = []
    samples_good_corpus: list[dict[str, str]] = []

    for row in iter_jsonl(path):
        route = str(row.get("llm_route") or "unknown")
        routes[route] += 1
        scenes[str(row.get("behavior_scene") or "unknown")] += 1
        reply = str(row.get("reply_text") or "").strip()
        user = str(row.get("user_text") or "").strip()
        reply_lengths.append(len(reply))
        if any(marker in reply for marker in _SERVICE_TONE_MARKERS):
            service_tone += 1
            if len(samples_service) < 5:
                samples_service.append({"user": user[:40], "reply": reply[:60], "route": route})
        route_bucket = top_replies_by_route.setdefault(route, Counter())
        route_bucket[reply] += 1
        if route.startswith("corpus_") and len(reply) <= 16 and len(samples_good_corpus) < 5:
            samples_good_corpus.append({"user": user[:40], "reply": reply, "route": route})

    total = sum(routes.values()) or 1
    corpus_total = sum(count for key, count in routes.items() if str(key).startswith("corpus_"))
    return {
        "total": total,
        "routes": dict(routes.most_common(12)),
        "scenes": dict(scenes.most_common(8)),
        "avg_reply_len": round(sum(reply_lengths) / len(reply_lengths), 1) if reply_lengths else 0,
        "max_reply_len": max(reply_lengths) if reply_lengths else 0,
        "service_tone_rate": round(service_tone / total, 3),
        "corpus_route_share": round(corpus_total / total, 3),
        "top_replies": {
            route: [text for text, _ in counter.most_common(3)]
            for route, counter in sorted(top_replies_by_route.items(), key=lambda item: -routes[item[0]])[:6]
        },
        "samples_service_tone": samples_service,
        "samples_good_corpus": samples_good_corpus,
    }


def evaluate_opportunity_quality(path: Path) -> dict[str, object]:
    actions: Counter[str] = Counter()
    accepted = 0
    rejected = 0
    skip_reasons: Counter[str] = Counter()
    pool_sizes: list[int] = []
    god_mode = 0
    for row in iter_jsonl(path):
        if row.get("kind") != "conversation_decision_trace":
            continue
        actions[str(row.get("action") or "")] += 1
        if row.get("opportunity_accepted"):
            accepted += 1
        else:
            rejected += 1
            skip_reasons[str(row.get("trace_reason") or "unknown")] += 1
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        pool = extra.get("candidate_pool_size")
        if isinstance(pool, int):
            pool_sizes.append(pool)
        mode = str(extra.get("reply_mode") or row.get("mode") or "")
        if mode == "god":
            god_mode += 1
    decided = accepted + rejected or 1
    return {
        "accepted": accepted,
        "rejected": rejected,
        "accept_rate": round(accepted / decided, 3),
        "actions": dict(actions.most_common(8)),
        "skip_reasons": dict(skip_reasons.most_common(6)),
        "avg_candidate_pool": round(sum(pool_sizes) / len(pool_sizes), 1) if pool_sizes else 0,
        "god_mode_share": round(god_mode / decided, 3),
    }


def build_evaluation_report(data_dir: Path | None) -> dict[str, object]:
    fb_path = feedback_entries_path_for(data_dir)
    ot_path = opportunity_trace_path(data_dir)
    feedback = evaluate_feedback_quality(fb_path) if fb_path.is_file() else {}
    opportunity = evaluate_opportunity_quality(ot_path) if ot_path.is_file() else {}

    findings: list[str] = []
    recommendations: list[str] = []

    if feedback:
        plain_share = feedback["routes"].get("plain_llm_chat", 0) / max(int(feedback["total"]), 1)
        if plain_share > 0.8:
            findings.append("@闲聊 plain_llm_chat 占主导（>80%），当前 feedback 主要反映闲聊而非接话 LLM。")
            recommendations.append("开启 repeater 任务 feedback 后，bias 应分路由统计（plain vs corpus_*）。")
        if float(feedback.get("service_tone_rate") or 0) > 0.05:
            findings.append("闲聊回复存在明显客服/博士口吻（service_tone_rate > 5%）。")
            recommendations.append(
                "收紧 @闲聊 system prompt：禁止「博士」「有啥想聊」等出戏词；优先改 persona。"
            )
        corpus_share = float(feedback.get("corpus_route_share") or 0)
        if corpus_share < 0.15:
            findings.append("corpus_* 路由样本偏少（<15%），接话 LLM 定向优化数据不足。")
            recommendations.append(
                "已扩展 repeater callback 采集；观察一周后 corpus 占比是否上升。"
            )

    if opportunity:
        accept_rate = float(opportunity.get("accept_rate") or 0)
        if accept_rate > 0.9:
            findings.append(
                f"opportunity_gate 通过率很高（{accept_rate:.0%}），需结合 skip 样本人工抽查。"
            )
        skip_n = int(opportunity.get("rejected") or 0)
        if skip_n > 0:
            recommendations.append(f"有 {skip_n} 条 skip trace，可 export-cases --action skip 做拒单回归。")
        rewrite_n = opportunity.get("actions", {}).get("reply_rewrite", 0)
        generate_n = opportunity.get("actions", {}).get("reply_generate", 0)
        if rewrite_n > generate_n * 2:
            findings.append("接话以 rewrite（polish_lite）为主，generate 较少；语料底盘覆盖较好。")
            recommendations.append("优化 polish_lite prompt：保持短句、禁止扩写；用 corpus_polish_lite 样本做 A/B。")

    return {
        "feedback": feedback,
        "opportunity": opportunity,
        "findings": findings,
        "recommendations": recommendations,
        "scorecard": {
            "chat_persona": "需改进" if float(feedback.get("service_tone_rate") or 0) > 0.05 else "尚可",
            "repeater_data_coverage": "不足" if float(feedback.get("corpus_route_share") or 0) < 0.15 else "够用",
            "opportunity_gate": "偏松" if float(opportunity.get("accept_rate") or 0) > 0.9 else "正常",
            "corpus_pipeline": "健康" if opportunity.get("actions", {}).get("reply_corpus", 0) > 500 else "待观察",
        },
    }


def cmd_evaluate(data_dir: Path | None) -> int:
    print(json.dumps(build_evaluation_report(data_dir), ensure_ascii=False, indent=2))
    return 0


def cmd_analyze(data_dir: Path | None) -> int:
    fb_path = feedback_entries_path_for(data_dir)
    ot_path = opportunity_trace_path(data_dir)
    mh_path = metrics_history_path(data_dir)

    report = {
        "feedback": analyze_feedback(fb_path) if fb_path.is_file() else {"path": str(fb_path), "total": 0},
        "opportunity_trace": analyze_opportunity(ot_path) if ot_path.is_file() else {"path": str(ot_path), "total": 0},
        "metrics_history_lines": sum(1 for _ in iter_jsonl(mh_path)) if mh_path.is_file() else 0,
        "optimization_hints": [
            "plain_llm_chat 占比高：优先优化 @闲聊人设与短句约束，而非接话 select。",
            "corpus_polish_lite / corpus_select 样本可喂给 tools/integration_repeater_llm.py 做回归。",
            "skip 类 decision_trace 可用来调 opportunity_gate 阈值，避免误开口。",
            "feedback top_replies 经 group_feedback_bias_snapshot 影响 repeater 偏好（需开启 bias）。",
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_export(data_dir: Path | None, *, limit: int, action: str, out: Path, only_accepted: bool) -> int:
    cases = export_replay_cases(
        opportunity_trace_path(data_dir),
        limit=limit,
        action=action,
        only_accepted=only_accepted,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case, ensure_ascii=False) + "\n")
    print(f"exported {len(cases)} cases -> {out}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="本地接话/LLM 评测数据分析与用例导出")
    parser.add_argument("--data-dir", type=Path, default=None, help="默认 data/pb_webui")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("analyze", help="汇总 feedback / opportunity_trace 统计")
    sub.add_parser("evaluate", help="基于本地数据输出评价结论与优化建议")

    export_p = sub.add_parser("export-cases", help="从 opportunity_trace 导出 replay 用例")
    export_p.add_argument("--limit", type=int, default=50)
    export_p.add_argument("--action", default="", help="如 reply_generate / reply_corpus / skip")
    export_p.add_argument("--out", type=Path, default=Path("data/eval/repeater_replay_cases.jsonl"))
    export_p.add_argument("--include-rejected", action="store_true")

    filter_p = sub.add_parser("export-filter-draft", help="从 feedback 导出输出后过滤词表评审草案")
    filter_p.add_argument("--out", type=Path, default=Path("data/eval/llm_output_filter_draft.json"))

    args = parser.parse_args()
    if args.command == "analyze":
        raise SystemExit(cmd_analyze(args.data_dir))
    if args.command == "evaluate":
        raise SystemExit(cmd_evaluate(args.data_dir))
    if args.command == "export-cases":
        raise SystemExit(
            cmd_export(
                args.data_dir,
                limit=args.limit,
                action=args.action,
                out=args.out,
                only_accepted=not args.include_rejected,
            )
        )
    if args.command == "export-filter-draft":
        raise SystemExit(cmd_export_filter_draft(args.data_dir, out=args.out))


if __name__ == "__main__":
    main()
