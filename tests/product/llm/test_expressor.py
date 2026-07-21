from __future__ import annotations

from pallas.product.llm.expressor import build_expressor_instruction, build_expressor_user_text


def test_expressor_instruction_asks_oral_rewrite() -> None:
    text = build_expressor_instruction()
    assert "口语" in text
    assert "勿扩写" in text


def test_expressor_user_text_wraps_raw_reply() -> None:
    text = build_expressor_user_text(
        user_text="今天好闲",
        raw_reply="感觉今天确实挺闲的呢",
        reason="口气偏客服",
    )
    assert "【用户消息】今天好闲" in text
    assert "【待改写】感觉今天确实挺闲的呢" in text
    assert "口气偏客服" in text
    assert "只输出一句" in text
