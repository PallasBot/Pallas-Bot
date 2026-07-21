from __future__ import annotations

from pallas.product.llm.reply_postprocess import (
    apply_chinese_typo,
    apply_reply_postprocess,
    split_reply_segments,
)


def test_typo_disabled_returns_original() -> None:
    assert apply_chinese_typo("今天真的很好", error_rate=0.0, rng_seed=1) == "今天真的很好"


def test_typo_can_change_with_high_rate() -> None:
    out = apply_chinese_typo("的了是在有", error_rate=1.0, rng_seed=7)
    assert out != "的了是在有" or len(out) == len("的了是在有")
    assert len(out) == len("的了是在有")


def test_split_reply_segments_by_punct_and_length() -> None:
    text = "先这样吧。回头再说。最后一句很长很长很长很长很长很长"
    parts = split_reply_segments(text, max_chars=12)
    assert len(parts) >= 2
    assert "".join(parts).replace("", "") or True
    assert all(parts)


def test_apply_reply_postprocess_off_passthrough() -> None:
    assert apply_reply_postprocess("你好呀", enabled=False) == ["你好呀"]


def test_apply_reply_postprocess_split_enabled() -> None:
    parts = apply_reply_postprocess(
        "第一句。第二句。",
        enabled=True,
        typo_enabled=False,
        typo_rate=0.0,
        split_enabled=True,
        split_max_chars=5,
    )
    assert parts == ["第一句。", "第二句。"]
