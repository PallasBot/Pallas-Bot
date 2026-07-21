from __future__ import annotations

from pallas.product.llm.reply_necessity import (
    REPLY_NECESSITY_TRIGGER_SCORE,
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
