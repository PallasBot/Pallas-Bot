"""LLM 输出守卫链骨架单元测试。"""

from __future__ import annotations

import pytest

from pallas.product.llm.guard import GuardChain, GuardVerdict


def _judge(decision: str, gate: str):
    def _inner(_ctx: dict) -> GuardVerdict:
        return GuardVerdict(gate=gate, decision=decision, reason="test")

    return _inner


def test_empty_chain_returns_allow() -> None:
    chain = GuardChain("unit")
    result = chain.run({})
    assert result.final.decision == "allow"
    assert result.final.reason == "empty_chain"
    assert result.verdicts == []


def test_chain_runs_in_registration_order() -> None:
    chain = GuardChain("unit")
    chain.register("first", _judge("retry", "first"))
    chain.register("second", _judge("block", "second"))
    result = chain.run({})
    assert [v.gate for v in result.verdicts] == ["first", "second"]
    assert result.final.gate == "second"
    assert result.final.decision == "block"
    assert result.stage == "unit"


def test_chain_final_is_last_verdict() -> None:
    chain = GuardChain("unit")
    chain.register("a", _judge("allow", "a"))
    chain.register("b", _judge("block", "b"))
    chain.register("c", _judge("silent", "c"))
    result = chain.run({})
    assert result.final.decision == "silent"
    assert result.final.gate == "c"


def test_missing_gate_raises() -> None:
    chain = GuardChain("unit")
    chain.register("only", _judge("allow", "only"))
    # 手动向顺序注入一个未注册 gate，校验不会静默跳过
    chain._order.append("missing")
    with pytest.raises(RuntimeError, match="未注册 gate"):
        chain.run({})


def test_register_duplicate_keeps_order() -> None:
    chain = GuardChain("unit")
    chain.register("g", _judge("allow", "g"))
    chain.register("g", _judge("block", "g"))
    chain.register("h", _judge("allow", "h"))
    result = chain.run({})
    assert [v.gate for v in result.verdicts] == ["g", "h"]
    assert result.verdicts[0].decision == "block"  # 覆盖生效
