from __future__ import annotations

import pytest

from pallas.product.llm.reply_necessity import (
    REPLY_NECESSITY_TRIGGER_SCORE,
    evaluate_reply_necessity_gate,
    is_bystander_plain_text,
    is_noise_fragment,
    is_short_vent,
    score_reply_necessity,
)


def test_noise_fragment_skips_single_letters_and_punct() -> None:
    assert is_noise_fragment("D") is True
    assert is_noise_fragment("？") is True
    assert is_noise_fragment("啊？") is False
    assert is_noise_fragment("在吗") is False


def test_bystander_detects_at_other_not_bot() -> None:
    assert is_bystander_plain_text("[CQ:at,qq=1001] 今晚开黑", bot_id=2002) is True
    assert is_bystander_plain_text("[CQ:at,qq=2002] 今晚开黑", bot_id=2002) is False
    assert is_bystander_plain_text("今晚开黑", bot_id=2002) is False


def test_necessity_high_for_to_me_or_question() -> None:
    hit = score_reply_necessity(
        text="这怎么弄？",
        is_to_me=True,
        bot_recently_replied=False,
        has_recent_back_and_forth=True,
        has_candidate_pool=True,
    )
    assert hit.score >= REPLY_NECESSITY_TRIGGER_SCORE


@pytest.mark.parametrize("text", ["没绷住", "我又改输出了，唉", "就是骂你"])
def test_direct_short_social_turn_does_not_cross_reply_necessity_threshold(text: str) -> None:
    result = evaluate_reply_necessity_gate(text=text, is_to_me=True)

    assert result.decision == "skip"
    assert result.score < REPLY_NECESSITY_TRIGGER_SCORE
    assert "low_social" in result.detail


@pytest.mark.parametrize("text", ["你还在吗", "这个怎么弄", "快回我", "继续说"])
def test_direct_question_or_request_still_crosses_reply_necessity_threshold(text: str) -> None:
    result = evaluate_reply_necessity_gate(text=text, is_to_me=True)

    assert result.decision == "proceed"
    assert result.score >= REPLY_NECESSITY_TRIGGER_SCORE


def test_direct_question_is_not_suppressed_by_recent_bot_presence() -> None:
    result = evaluate_reply_necessity_gate(
        text="这个怎么弄",
        is_to_me=True,
        recent_bot_reply_count=6,
    )

    assert result.decision == "proceed"
    assert result.score >= REPLY_NECESSITY_TRIGGER_SCORE


def test_mentioned_question_crosses_reply_necessity_threshold() -> None:
    result = evaluate_reply_necessity_gate(text="牛牛你还在吗", is_mentioned=True)

    assert result.decision == "proceed"
    assert result.score >= REPLY_NECESSITY_TRIGGER_SCORE


def test_mentioned_short_social_turn_crosses_reply_necessity_threshold() -> None:
    result = evaluate_reply_necessity_gate(
        text="牛牛晚饭吃了没",
        is_mentioned=True,
        has_recent_back_and_forth=True,
    )

    assert result.decision == "proceed"
    assert result.score >= REPLY_NECESSITY_TRIGGER_SCORE


@pytest.mark.parametrize(
    ("kwargs", "name"),
    [
        ({"is_mentioned": True}, "mention"),
        ({"is_followup": True}, "followup"),
    ],
)
def test_addressed_question_is_not_suppressed_by_recent_bot_presence(
    kwargs: dict[str, bool],
    name: str,
) -> None:
    result = evaluate_reply_necessity_gate(
        text="你还在吗",
        recent_bot_reply_count=6,
        **kwargs,
    )

    assert result.decision == "proceed", name
    assert result.score >= REPLY_NECESSITY_TRIGGER_SCORE
    assert "bot_presence_exempt" in result.detail


def test_reply_necessity_applies_recent_bot_presence_penalty() -> None:
    result = evaluate_reply_necessity_gate(
        text="这也太离谱了",
        is_mentioned=True,
        recent_bot_reply_count=4,
    )

    assert result.decision == "skip"
    assert "bot_presence" in result.detail


def test_necessity_low_for_short_reaction_after_bot_spoke() -> None:
    hit = score_reply_necessity(
        text="哈哈",
        is_to_me=False,
        bot_recently_replied=True,
        has_recent_back_and_forth=False,
        has_candidate_pool=False,
    )
    assert hit.score < REPLY_NECESSITY_TRIGGER_SCORE


def test_necessity_low_for_bystander() -> None:
    hit = score_reply_necessity(
        text="[CQ:at,qq=1001] 你先说",
        is_to_me=False,
        bot_id=2002,
        bot_recently_replied=False,
        has_recent_back_and_forth=True,
        has_candidate_pool=True,
    )
    assert hit.score < REPLY_NECESSITY_TRIGGER_SCORE


def test_noise_fragment_treats_emoji_as_noise() -> None:
    assert is_noise_fragment("🤔") is True
    assert is_noise_fragment("🥰🥰") is True
    assert is_noise_fragment("在吗") is False


def test_spam_promo_and_incomplete() -> None:
    from pallas.product.llm.reply_necessity import is_incomplete_utterance, looks_like_spam_or_promo

    assert looks_like_spam_or_promo("⚡️不用下载点击即玩⚡️：https://www.bilibili.com/toy/x") is True
    assert is_incomplete_utterance("你是") is True
    hit = score_reply_necessity(
        text="无聊妹子来",
        is_to_me=False,
        has_recent_back_and_forth=True,
        has_candidate_pool=True,
    )
    assert hit.score < REPLY_NECESSITY_TRIGGER_SCORE


def test_is_short_vent_accepts_compact_complaints() -> None:
    assert is_short_vent("又临时改了，烦")
    assert is_short_vent("今天真累")


def test_is_short_vent_rejects_noise_and_long_text() -> None:
    assert not is_short_vent("哈哈哈")
    assert not is_short_vent("这件事已经让我非常烦了，而且我还没想好怎么处理")


def test_affinity_penalizes_ambient_low_affinity() -> None:
    base = evaluate_reply_necessity_gate(
        text="今天天气不错",
        bot_id=1,
    )
    penalized = evaluate_reply_necessity_gate(
        text="今天天气不错",
        bot_id=1,
        user_affinity=-1.0,
    )
    assert penalized.score < base.score
    assert "affinity" in penalized.detail


def test_affinity_does_not_penalize_to_me() -> None:
    gate = evaluate_reply_necessity_gate(
        text="@bot 这个怎么弄？",
        bot_id=1,
        is_to_me=True,
        user_affinity=-1.0,
    )
    assert gate.decision == "proceed"
    assert "affinity" not in gate.detail


def test_affinity_no_penalty_above_threshold() -> None:
    gate = evaluate_reply_necessity_gate(
        text="今天天气不错",
        bot_id=1,
        user_affinity=0.0,
    )
    assert "affinity" not in gate.detail


def test_replied_recent_message_crosses_threshold() -> None:
    gate = evaluate_reply_necessity_gate(
        text="哈哈哈哈哈",
        replied_recent_message=True,
    )
    assert gate.decision == "proceed"
    assert "replied_recent" in gate.detail
    assert gate.score >= REPLY_NECESSITY_TRIGGER_SCORE


def test_replied_recent_message_does_not_rescue_noise_or_spam() -> None:
    noise = evaluate_reply_necessity_gate(
        text="😄😄😄",
        replied_recent_message=True,
    )
    assert noise.decision == "skip"
    assert "replied_recent" not in noise.detail

    spam = evaluate_reply_necessity_gate(
        text="点击即玩 免费领",
        replied_recent_message=True,
    )
    assert spam.decision == "skip"
    assert "replied_recent" not in spam.detail


def test_replied_recent_without_recent_message_stays_skip() -> None:
    gate = evaluate_reply_necessity_gate(
        text="哈哈哈哈哈",
        replied_recent_message=False,
    )
    assert gate.decision == "skip"
    assert "replied_recent" not in gate.detail
