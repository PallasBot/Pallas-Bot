from __future__ import annotations

from pallas.product.llm.feedback_chat_hint import (
    build_group_feedback_chat_hint,
    correction_matches_query,
    summarize_reply_snippet,
)
from pallas.product.llm.repeater_feedback import (
    append_feedback_entry,
    build_feedback_entry,
    set_feedback_entry_eligibility,
)
from pallas.product.persona.self_identity import parse_self_alias_teach


def test_summarize_reply_snippet_strips_kaomoji() -> None:
    assert summarize_reply_snippet("哞~ 好呀！(*^_^*)") == "哞~ 好呀"


def test_build_group_feedback_chat_hint_lists_good_and_avoid(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_REPEATER_FEEDBACK_ENABLED", "true")
    monkeypatch.setenv("LLM_CHAT_ENABLED", "true")
    monkeypatch.setenv("LLM_REPEATER_BIAS_ENABLED", "true")
    from pallas.product.llm.config import clear_llm_config_cache

    clear_llm_config_cache()

    append_feedback_entry(
        build_feedback_entry(
            bot_id=1,
            group_id=123,
            user_id=1,
            request_id="good1",
            user_text="你好",
            reply_text="行啊，就这样。",
        )
    )
    append_feedback_entry(
        build_feedback_entry(
            bot_id=1,
            group_id=123,
            user_id=1,
            request_id="bad1",
            user_text="你好",
            reply_text="哞~ 好呀！(*^_^*)",
        )
    )
    set_feedback_entry_eligibility(request_id="bad1", eligible_for_bias=False)

    hint = build_group_feedback_chat_hint(group_id=123)

    assert "【维护者样本参考】" in hint
    assert "较好的接话可参考" in hint
    assert "已被维护者排除" in hint
    assert "哞~ 好呀" in hint


def test_build_group_feedback_chat_hint_includes_maintainer_correction(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_REPEATER_FEEDBACK_ENABLED", "true")
    monkeypatch.setenv("LLM_CHAT_ENABLED", "true")
    monkeypatch.setenv("LLM_REPEATER_BIAS_ENABLED", "true")
    from pallas.product.llm.config import clear_llm_config_cache

    clear_llm_config_cache()

    append_feedback_entry(
        build_feedback_entry(
            bot_id=1,
            group_id=123,
            user_id=1,
            request_id="corr1",
            user_text="牛牛真棒",
            reply_text="谢谢夸奖 (*^_^*)",
            corrected_reply_text="谢谢，还行吧",
            corrected_at=1718700001,
        )
    )

    hint = build_group_feedback_chat_hint(group_id=123, user_text="牛牛真棒啊")

    assert "维护者期望类似这样接" in hint
    assert "谢谢，还行吧" in hint
    assert correction_matches_query("牛牛真棒", "牛牛真棒啊") is True


def test_build_group_feedback_chat_hint_contrast_pair(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_REPEATER_FEEDBACK_ENABLED", "true")
    monkeypatch.setenv("LLM_CHAT_ENABLED", "true")
    monkeypatch.setenv("LLM_REPEATER_BIAS_ENABLED", "true")
    from pallas.product.llm.config import clear_llm_config_cache

    clear_llm_config_cache()

    append_feedback_entry(
        build_feedback_entry(
            bot_id=1,
            group_id=55,
            user_id=1,
            request_id="pair-bad",
            user_text="今天好闲",
            reply_text="您好，很高兴为您服务",
        )
    )
    set_feedback_entry_eligibility(request_id="pair-bad", eligible_for_bias=False)
    append_feedback_entry(
        build_feedback_entry(
            bot_id=1,
            group_id=55,
            user_id=1,
            request_id="pair-good",
            user_text="今天好闲",
            reply_text="那确实闲",
            corrected_reply_text="那确实闲",
            corrected_at=1718700002,
        )
    )

    hint = build_group_feedback_chat_hint(group_id=55, user_text="今天好闲啊")
    assert "别写「您好，很高兴为您服务」" in hint or "别写" in hint
    assert "可写「那确实闲」" in hint


def test_build_group_feedback_chat_hint_skips_filler_good(tmp_path, monkeypatch) -> None:
    from pallas.product.llm.feedback_chat_hint import is_weak_good_feedback_snippet

    assert is_weak_good_feedback_snippet("还行吧") is True
    assert is_weak_good_feedback_snippet("那确实闲") is False

    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_REPEATER_FEEDBACK_ENABLED", "true")
    monkeypatch.setenv("LLM_CHAT_ENABLED", "true")
    monkeypatch.setenv("LLM_REPEATER_BIAS_ENABLED", "true")
    from pallas.product.llm.config import clear_llm_config_cache

    clear_llm_config_cache()

    append_feedback_entry(
        build_feedback_entry(
            bot_id=1,
            group_id=77,
            user_id=1,
            request_id="ok-good",
            user_text="今天好闲",
            reply_text="那确实闲",
        )
    )
    append_feedback_entry(
        build_feedback_entry(
            bot_id=1,
            group_id=77,
            user_id=1,
            request_id="filler-good",
            user_text="666",
            reply_text="还行吧",
        )
    )

    hint = build_group_feedback_chat_hint(group_id=77)
    assert "那确实闲" in hint
    if "较好的接话可参考" in hint:
        good_part = hint.split("较好的接话可参考：", 1)[1].split("\n")[0]
        assert "还行吧" not in good_part


def test_build_group_feedback_chat_hint_skips_canned_capability_good_samples(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_REPEATER_FEEDBACK_ENABLED", "true")
    monkeypatch.setenv("LLM_CHAT_ENABLED", "true")
    monkeypatch.setenv("LLM_REPEATER_BIAS_ENABLED", "true")
    from pallas.product.llm.config import clear_llm_config_cache

    clear_llm_config_cache()

    append_feedback_entry(
        build_feedback_entry(
            bot_id=1,
            group_id=626,
            user_id=1,
            request_id="canned-cap",
            user_text="有啥功能",
            reply_text="能聊聊天、接接梗、陪你唠嗑儿，反正群里有啥话题我就跟着接两句。",
        )
    )
    append_feedback_entry(
        build_feedback_entry(
            bot_id=1,
            group_id=626,
            user_id=1,
            request_id="real-good",
            user_text="今天吃啥",
            reply_text="随便，泡面也行。",
        )
    )

    from pallas.product.llm.feedback_chat_hint import is_weak_good_feedback_snippet

    assert is_weak_good_feedback_snippet("能聊聊天、接接梗、陪你唠嗑儿，反正群里有啥话题我就跟着接两句。")
    hint = build_group_feedback_chat_hint(group_id=626, user_text="有什么用呢")
    assert "能聊聊天" not in hint
    assert "接接梗" not in hint
    assert "泡面也行" in hint


def test_build_group_feedback_chat_hint_empty_when_bias_disabled(monkeypatch) -> None:
    monkeypatch.setenv("LLM_CHAT_ENABLED", "true")
    monkeypatch.delenv("LLM_REPEATER_BIAS_ENABLED", raising=False)
    from pallas.product.llm.config import clear_llm_config_cache

    clear_llm_config_cache()
    assert build_group_feedback_chat_hint(group_id=123) == ""


def test_parse_self_alias_teach() -> None:
    assert parse_self_alias_teach("牛牛就是我") == ["牛牛"]
    assert parse_self_alias_teach("记住：牛牛指的是你") == ["牛牛"]
    assert parse_self_alias_teach("牛牛=你") == ["牛牛"]
    assert parse_self_alias_teach("漂亮牛牛就是你") == ["漂亮牛牛"]
    assert parse_self_alias_teach("今天吃什么") == []


def test_parse_self_alias_observe() -> None:
    from pallas.product.persona.self_identity import parse_self_alias_observe

    assert parse_self_alias_observe("大家叫你漂亮牛牛") == ["漂亮牛牛"]
    assert parse_self_alias_observe("你是漂亮牛牛") == ["漂亮牛牛"]
    assert parse_self_alias_observe("你的外号是漂亮牛") == ["漂亮牛"]
    assert parse_self_alias_observe("你是谁") == []
    assert parse_self_alias_observe("今天吃什么") == []
    # teach 优先，observe 不重复吃
    assert parse_self_alias_observe("漂亮牛牛就是你") == []
