from __future__ import annotations


def test_current_time_prompt_block_identifies_shanghai_time() -> None:
    from pallas.product.llm.assembler.chat_prompt import ChatPromptAssembler

    block = ChatPromptAssembler.current_time_block("2026-08-26 12:34:56")

    assert "Asia/Shanghai" in block
    assert "2026-08-26 12:34:56" in block
    assert "本轮" in block
