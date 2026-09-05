"""LLM 输出守卫链：把分散在各生命周期的行为守卫收敛为一个可审计的执行骨架。

守卫链只做「注册 + 顺序 + 裁决日志」的编排，不复制守卫实现分支逻辑——
每个 gate 是既有守卫函数的薄适配器，返回统一 GuardVerdict。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

_JUDGE = Callable[[dict], "GuardVerdict"]

_GATE_NOT_FOUND_SUGGESTION = (
    "守卫链未注册 gate [{}]。请先 register_gate() 再 run()，避免守卫静默跳过导致审计记录不完整。"
)


@dataclass(frozen=True, slots=True)
class GuardVerdict:
    """单守卫裁决。decision ∈ {allow, block, retry, silent}，随阶段而异。"""

    gate: str
    decision: str
    reason: str = ""
    payload: dict | None = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GuardChainResult:
    """整条守卫链的裁决记录，可持久化供离线审计。"""

    stage: str
    verdicts: list[GuardVerdict]
    final: GuardVerdict


class GuardChain:
    """按声明顺序执行一组命名 gate。每个 gate 是 ``(ctx) -> GuardVerdict`` 的适配器。"""

    def __init__(self, stage: str) -> None:
        self._stage = stage
        self._gates: dict[str, GuardVerdict] = {}
        self._order: list[str] = []

    def register(self, gate: str, judge: _JUDGE) -> None:
        """注册 gate。gate 名须唯一，重复注册直接覆盖并保持原顺序。"""
        self._gates[gate] = judge
        if gate not in self._order:
            self._order.append(gate)

    def run(self, ctx: dict) -> GuardChainResult:
        """顺序执行全部 gate，返回全链裁决（含最终裁决）。空链返回 allow。"""
        verdicts: list[GuardVerdict] = []
        for gate in self._order:
            judge = self._gates.get(gate)
            if judge is None:
                raise RuntimeError(_GATE_NOT_FOUND_SUGGESTION.format(gate))
            verdicts.append(judge(ctx))
        final = verdicts[-1] if verdicts else GuardVerdict(gate="<chain>", decision="allow", reason="empty_chain")
        return GuardChainResult(stage=self._stage, verdicts=verdicts, final=final)
