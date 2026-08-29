from __future__ import annotations

from pallas.product.persona.affect_lexicon import load_affect_lexicon, punct_aggression_score
from pallas.product.persona.prompt_guard import sanitize_prompt_literal


def infer_expression_affect_stance(text: str) -> str:
    plain = sanitize_prompt_literal(str(text or "").strip(), max_len=64).lower()
    if not plain:
        return "neutral"

    lex = load_affect_lexicon()
    if any(token in plain for token in lex["polite"]):
        return "warm"
    complain_markers = (
        "太",
        "离谱",
        "黑了",
        "真的黑",
        "什么鬼",
        "搞什么",
        "有病",
        "逆天",
        "绷不住",
        "服了",
        "抽卡",
        "有点狠",
    )
    if (
        any(token in plain for token in lex["harsh"])
        or punct_aggression_score(plain) >= 0.2
        or any(token in plain for token in complain_markers)
    ):
        return "complain"
    if any(token in plain for token in ("确实", "也是", "对啊", "行啊", "是啊", "还真是")):
        return "echo"
    return "neutral"
