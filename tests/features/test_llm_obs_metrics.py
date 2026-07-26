"""立项用观测打点：speak / reply_gate 原因 / selective / tool_session。"""

from __future__ import annotations

from pallas.product.llm.reply_gate import evaluate_llm_reply_gate_result, reply_gate_skip_metric
from pallas.product.llm.speak_perception import SpeakDecision, speak_perception_metrics
from pallas.product.llm.task_metrics import (
    clear_llm_task_metrics_for_tests,
    llm_task_metrics_snapshot,
    record_bot_llm_task,
)
from pallas.product.llm.tools.registry import tool_metadata_for_chat


def test_reply_gate_skip_reason_metrics() -> None:
    result = evaluate_llm_reply_gate_result("[CQ:face,id=1]")
    assert result.decision == "skip"
    assert result.reason == "face"
    assert reply_gate_skip_metric(result.reason) == "reply_gate_skip_face"


def test_speak_perception_metrics_buckets() -> None:
    assert speak_perception_metrics(SpeakDecision(True, "mention", 100)) == ("speak_mention",)
    assert speak_perception_metrics(SpeakDecision(False, "ambient_miss", 10)) == (
        "speak_skip",
        "speak_skip_ambient",
    )
    assert speak_perception_metrics(SpeakDecision(False, "command", 0)) == (
        "speak_skip",
        "speak_skip_command",
    )


def test_selective_empty_and_hit_recorded(monkeypatch) -> None:
    clear_llm_task_metrics_for_tests()

    class _Cfg:
        llm_tools_enabled = True
        llm_tools_selective = True
        llm_tools_blacklist: list[str] = []

    monkeypatch.setattr(
        "pallas.product.llm.tools.registry.get_llm_config",
        lambda: _Cfg(),
    )
    monkeypatch.setattr(
        "pallas.product.llm.tools.registry.tool_catalog_for_chat",
        lambda **_kwargs: None,
    )
    assert tool_metadata_for_chat(task="llm_chat", user_text="今天天气不错") == {}
    snap = llm_task_metrics_snapshot()
    assert snap["by_task"]["llm_chat"]["selective_empty"] == 1
    clear_llm_task_metrics_for_tests()


def test_record_new_events_accepted() -> None:
    clear_llm_task_metrics_for_tests()
    for event in (
        "speak_skip",
        "selective_hit",
        "tool_call_ok",
        "tool_session_no_call",
        "reply_gate_skip_noise",
    ):
        record_bot_llm_task("llm_chat", event)
    snap = llm_task_metrics_snapshot()
    row = snap["by_task"]["llm_chat"]
    assert row["speak_skip"] == 1
    assert row["selective_hit"] == 1
    assert row["tool_call_ok"] == 1
    assert row["tool_session_no_call"] == 1
    assert row["reply_gate_skip_noise"] == 1
    clear_llm_task_metrics_for_tests()
