from __future__ import annotations

import pytest

from pallas.product.llm.reply_necessity import (
    REPLY_NECESSITY_TRIGGER_SCORE,
    evaluate_reply_necessity_gate,
    is_bystander_plain_text,
    is_noise_fragment,
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
