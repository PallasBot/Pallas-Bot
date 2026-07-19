from __future__ import annotations

import time

from pallas.product.persona.cross_group_profiler import group_style_weight


def _style_profile(*, answer_count: int, message_count: int, msg_skip: int = 0, ans_skip: int = 0) -> dict:
    return {
        "version": 1,
        "updated_at": int(time.time()),
        "sample": {
            "window_hours": 168,
            "message_count": message_count,
            "answer_count": answer_count,
            "distinct_answer_keywords": max(1, answer_count // 2),
            "contamination_skipped": {
                "message_count": msg_skip,
                "answer_count": ans_skip,
            },
        },
        "derived": {
            "reply_bias_mul": 1.1,
            "speak_bias_mul": 1.0,
            "length_pref": "short",
            "chaos_bias": 0.1,
        },
    }


def test_group_style_weight_downweights_high_contamination_ratio() -> None:
    clean = _style_profile(answer_count=20, message_count=32, msg_skip=0, ans_skip=0)
    dirty = _style_profile(answer_count=20, message_count=32, msg_skip=20, ans_skip=10)
    now = int(time.time())
    assert group_style_weight(dirty, now_ts=now) < group_style_weight(clean, now_ts=now)
