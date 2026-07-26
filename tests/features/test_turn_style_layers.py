"""本轮行为/措辞分层与概率换风格。"""

from __future__ import annotations

import random

from pallas.product.llm.models import ChatCompletionMessage
from pallas.product.llm.turn_style_layers import (
    build_probabilistic_alt_style_hint,
    build_turn_behavior_block,
    build_turn_wording_user_hints,
    merge_style_hints_before_last_user,
)
from pallas.product.persona.catchphrase_bank import (
    compile_catchphrase_prompt_lines,
    list_catchphrases,
    promote_catchphrase,
    propose_catchphrase_from_bot_success,
    select_catchphrases_for_turn,
)


def test_probabilistic_alt_style_respects_rng() -> None:
    always = build_probabilistic_alt_style_hint(probability=1.0, rng=random.Random(0))
    never = build_probabilistic_alt_style_hint(probability=0.0, rng=random.Random(0))
    assert always.startswith("【本轮临时措辞】")
    assert never == ""


def test_behavior_and_wording_split() -> None:
    behavior = build_turn_behavior_block("【本轮行为参考】\n- 短回", "")
    assert "只管怎么接" in behavior
    hints = build_turn_wording_user_hints("【表达参考】x", "", "【本轮临时措辞】y")
    assert hints == ["【表达参考】x", "【本轮临时措辞】y"]


def test_merge_style_hints_before_last_user() -> None:
    messages = [
        ChatCompletionMessage(role="user", content="hi"),
        ChatCompletionMessage(role="assistant", content="yo"),
        ChatCompletionMessage(role="user", content="翻译成中文"),
    ]
    merged = merge_style_hints_before_last_user(messages, ["【本轮临时措辞】短一点"])
    assert [m.role for m in merged] == ["user", "assistant", "user", "user"]
    assert merged[-2].content.startswith("【本轮临时措辞】")
    assert merged[-1].content == "翻译成中文"


def test_catchphrase_selects_by_scene_and_text(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PALLAS_DATA_DIR", str(tmp_path))
    propose_catchphrase_from_bot_success(42, 1, "那很牛了", "接梗玩笑")
    propose_catchphrase_from_bot_success(42, 2, "那很牛了", "接梗玩笑")
    propose_catchphrase_from_bot_success(42, 3, "那很牛了", "接梗玩笑")

    row = next(item for item in list_catchphrases(42) if item.saying == "那很牛了")
    promote_catchphrase(row.entry_id, force=True)
    picked = select_catchphrases_for_turn(42, user_text="这个梗典炸了", scene="banter", limit=2)
    assert picked
    assert picked[0].saying == "那很牛了"
    lines = compile_catchphrase_prompt_lines(42, user_text="这个梗典炸了", scene="banter", limit=2)
    assert any("那很牛了" in line for line in lines)
    assert compile_catchphrase_prompt_lines(42, limit=0) == []
