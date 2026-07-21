from __future__ import annotations

from pallas.product.llm.config import LlmConfig
from pallas.product.llm.reply_gate import evaluate_llm_reply_gate, is_shut_up_request
from pallas.product.llm.situational_rules import match_situational_rules


def test_is_shut_up_request() -> None:
    assert is_shut_up_request("牛牛，你能不能不要说话") is True
    assert is_shut_up_request("闭嘴") is True
    assert is_shut_up_request("今天吃什么") is False


def test_reply_gate_skips_shut_up_and_incomplete(monkeypatch) -> None:
    monkeypatch.setattr(
        "pallas.product.llm.config.get_llm_config",
        lambda: LlmConfig(llm_reply_gate_enabled=True, llm_reply_gate_min_chars=0),
    )
    assert evaluate_llm_reply_gate("你能不能不要说话") == "skip"
    assert evaluate_llm_reply_gate("你是") == "skip"
    assert evaluate_llm_reply_gate("在吗") == "proceed"


def test_situational_rules_match_shut_up_and_model_meta() -> None:
    shut = match_situational_rules("牛牛闭嘴", limit=3)
    assert any(item["name"] == "shut_up" for item in shut)
    meta = match_situational_rules("你配的是什么模型", limit=3)
    assert any(item["name"] == "model_meta_probe" for item in meta)
