#!/usr/bin/env python3
"""晋升候选 dry-run 报告：列出建议 promote / reject，不写盘。

用法:
  uv run python tools/report_promotion_candidates.py
  uv run python tools/report_promotion_candidates.py --limit 40 --write-json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pallas.product.llm.promotion_candidates import _load_candidates_index  # noqa: E402
from pallas.product.llm.repeater_feedback import (  # noqa: E402
    LlmRepeaterFeedbackEntry,
    feedback_base_dir,
    is_reply_safe_for_auto_promote,
    is_systemish_promote_text,
)
from tools.clean_llm_feedback import (  # noqa: E402
    classify_bad_entry,
    is_natural_short_corpus_reply,
    strip_cq,
)

_SKIP_PROMOTE = re.compile(r"(扩列|互赞|交际|高潮|上床|色色|涩涩)")


def score_pending(*, limit: int) -> tuple[list[dict], list[dict], list[dict]]:
    rows = _load_candidates_index()
    promote: list[dict] = []
    reject: list[dict] = []
    hold: list[dict] = []
    for candidate in rows.values():
        if candidate.promoted or str(candidate.rejected_reason or "").strip():
            continue
        trigger = str(candidate.trigger_text or "").strip()
        reply = str(candidate.reply_text or "").strip()
        plain = strip_cq(reply)
        fake = LlmRepeaterFeedbackEntry(
            entry_id=candidate.candidate_id,
            created_at=0,
            bot_id=0,
            group_id=int(candidate.group_id or 0),
            user_id=0,
            request_id=candidate.candidate_id,
            user_text=trigger,
            reply_text=reply,
            llm_route="corpus_select",
        )
        bad = classify_bad_entry(fake)
        support = int(candidate.support_count or 0)
        payload = {
            "candidate_id": candidate.candidate_id,
            "group_id": int(candidate.group_id or 0),
            "support_count": support,
            "trigger_text": trigger,
            "reply_text": reply,
            "bad_reasons": bad,
        }
        if is_systemish_promote_text(trigger, reply):
            payload["action"] = "reject"
            payload["reason"] = "系统/欢迎/警告类"
            reject.append(payload)
            continue
        if _SKIP_PROMOTE.search(trigger) or _SKIP_PROMOTE.search(reply):
            payload["action"] = "reject"
            payload["reason"] = "扩列/低质主题"
            reject.append(payload)
            continue
        if bad and not (
            set(bad) <= {"过短碎片", "长问短答"} and is_natural_short_corpus_reply(user=trigger, plain=plain)
        ):
            payload["action"] = "reject"
            payload["reason"] = ",".join(bad[:2])
            reject.append(payload)
            continue
        if not is_reply_safe_for_auto_promote(reply, trigger_text=trigger):
            payload["action"] = "reject"
            payload["reason"] = "写回不安全"
            reject.append(payload)
            continue
        if support >= 3 and (not bad or is_natural_short_corpus_reply(user=trigger, plain=plain)):
            payload["action"] = "promote"
            payload["reason"] = "高支持可参考"
            promote.append(payload)
            continue
        payload["action"] = "hold"
        payload["reason"] = "支持不足或待人工"
        hold.append(payload)

    promote.sort(key=lambda row: -int(row["support_count"]))
    reject.sort(key=lambda row: -int(row["support_count"]))
    hold.sort(key=lambda row: -int(row["support_count"]))
    return promote[:limit], reject[:limit], hold[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--write-json", action="store_true", help="写入 data/.../promotion_report_*.json")
    args = parser.parse_args()
    promote, reject, hold = score_pending(limit=max(1, int(args.limit)))
    print("=== report_promotion_candidates ===")
    print(f"建议 promote: {len(promote)}")
    for row in promote[:20]:
        print(
            f"  +sup={row['support_count']} Q={row['trigger_text'][:28]!r} A={row['reply_text'][:32]!r} "
            f"id={row['candidate_id']}"
        )
    print(f"建议 reject: {len(reject)}")
    for row in reject[:15]:
        print(
            f"  -sup={row['support_count']} [{row['reason']}] Q={row['trigger_text'][:24]!r} "
            f"A={row['reply_text'][:28]!r}"
        )
    print(f"hold 预览: {len(hold)}")
    if args.write_json:
        out_dir = feedback_base_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        path = out_dir / f"promotion_report_{stamp}.json"
        path.write_text(
            json.dumps(
                {"generated_at": int(time.time()), "promote": promote, "reject": reject, "hold": hold},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n已写入: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
