from __future__ import annotations

import json

from tools.eval_repeater_local import build_output_filter_draft


def test_build_output_filter_draft_tiers(tmp_path) -> None:
    path = tmp_path / "entries.jsonl"
    rows = [
        {
            "llm_route": "plain_llm_chat",
            "user_text": "在吗",
            "reply_text": "博士您好，有什么想聊的吗？",
        },
        {
            "llm_route": "plain_llm_chat",
            "user_text": "你好",
            "reply_text": "你好呀",
        },
        {
            "llm_route": "corpus_polish_lite",
            "user_text": "哈哈",
            "reply_text": "因为一般来说这样总结起来会更自然一些",
        },
    ]
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    draft = build_output_filter_draft(path)
    tiers = draft["tiers"]
    chat_tiers = tiers["chat_hard_block"] + tiers["chat_soft_retry"] + tiers["observe_only"]
    assert "博士" in chat_tiers
    assert draft["review_policy"]
    assert draft["already_in_feedback_gate"]
