from __future__ import annotations

from pallas.product.llm.repeater_feedback import LlmRepeaterFeedbackEntry
from tools.clean_llm_feedback import classify_bad_entry


def build_entry(**kwargs) -> LlmRepeaterFeedbackEntry:
    payload = {
        "entry_id": "e1",
        "created_at": 1,
        "bot_id": 1,
        "group_id": 123,
        "user_id": 2,
        "request_id": "e1",
        "user_text": "",
        "reply_text": "",
    }
    payload.update(kwargs)
    return LlmRepeaterFeedbackEntry(**payload)


def test_classify_cq_echo() -> None:
    entry = build_entry(
        user_text="能不能踢了这人机",
        reply_text="[CQ:at,qq=1] 能不能踢了这人机",
        llm_route="plain_llm_chat",
    )
    reasons = classify_bad_entry(entry)
    assert "含CQ码" in reasons
    assert "@自复读" in reasons


def test_classify_corpus_fragment() -> None:
    entry = build_entry(
        user_text="王者荣耀水晶换哪个比较好",
        reply_text="诶",
        llm_route="corpus_select",
    )
    assert "过短碎片" in classify_bad_entry(entry)


def test_classify_soft_template() -> None:
    entry = build_entry(
        user_text="搞么子",
        reply_text="哎呀，心情不太好嘛。发生了什么事吗？需要聊聊散散心哦。",
        llm_route="plain_llm_chat",
    )
    reasons = classify_bad_entry(entry)
    assert "软续聊模板" in reasons


def test_classify_keeps_meme_corpus() -> None:
    entry = build_entry(
        user_text="什么意思",
        reply_text="看不懂捏",
        llm_route="corpus_select",
    )
    assert classify_bad_entry(entry) == []


def test_classify_keeps_natural_short_corpus() -> None:
    entry = build_entry(
        user_text="哦哦",
        reply_text="懂了",
        llm_route="corpus_select",
    )
    assert classify_bad_entry(entry) == []


def test_classify_insult_mismatch() -> None:
    entry = build_entry(
        user_text="我去你个屎赶紧爬走",
        reply_text="大家晚上好啊",
        llm_route="corpus_select",
    )
    assert "骂战乱接" in classify_bad_entry(entry)


def test_systemish_promote_text_blocks_welcome() -> None:
    from pallas.product.llm.repeater_feedback import is_reply_safe_for_auto_promote, is_systemish_promote_text

    assert is_systemish_promote_text("欢迎老师加入本群，请遵守群规哦~", "大佬们好")
    assert not is_reply_safe_for_auto_promote(
        "大佬们好",
        trigger_text="欢迎老师加入本群，请遵守群规哦~",
    )
    assert is_systemish_promote_text("🤔", "（亚托莉思考中…）")
    assert not is_systemish_promote_text("哦哦", "懂了")
