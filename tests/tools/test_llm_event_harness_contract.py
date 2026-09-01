from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from tools import llm_event_harness as tool

if TYPE_CHECKING:
    from pathlib import Path


def test_result_as_dict_redacts_body_and_exposes_stable_fields() -> None:
    result = tool.EventResult(
        variant="A",
        case="command.success",
        status="delivered",
        journey="command",
        route="direct",
        request_id="req-1",
        reply="secret reply body",
        outbound_actions=[{"action": "send_group_msg", "params": {"group_id": 20002, "message": "secret reply body"}}],
        api_calls=[{"action": "send_group_msg", "params": {"group_id": 20002, "message": "secret reply body"}}],
        stages=[{"stage": "delivery", "status": "delivered"}],
        assertions={"outbound": 1},
        error=None,
        error_class=None,
        redaction_summary={"mask": tool.REDACTION_MASK},
    )

    row = result.as_dict(redact=True)

    assert row["case"] == "command.success"
    assert row["status"] == "delivered"
    assert row["journey"] == "command"
    assert row["route"] == "direct"
    assert row["request_id"] == "req-1"
    assert row["reply"] == tool.REDACTION_MASK
    assert row["outbound_actions"][0]["params"]["message"] == tool.REDACTION_MASK
    assert row["api_calls"][0]["params"]["message"] == tool.REDACTION_MASK
    assert row["stages"] == [{"stage": "delivery", "status": "delivered"}]
    # stable contract keys are always present
    for key in (
        "case",
        "status",
        "journey",
        "route",
        "request_id",
        "reply",
        "outbound_actions",
        "api_calls",
        "stages",
        "assertions",
        "error",
        "error_class",
        "prompt_hits",
        "redaction_summary",
    ):
        assert key in row


def test_result_as_dict_without_redact_keeps_raw_body_for_debug_tools() -> None:
    result = tool.EventResult(
        variant="A",
        case="cli",
        status="delivered",
        journey="llm",
        reply="visible reply",
        api_calls=[{"action": "send_group_msg", "params": {"message": "visible reply"}}],
    )

    row = result.as_dict()

    assert row["reply"] == "visible reply"
    assert row["api_calls"][0]["params"]["message"] == "visible reply"


def test_redact_stage_masks_body_content_keys() -> None:
    stage = {
        "stage": "provider",
        "status": "prompted",
        "system": "do not leak",
        "system_prefix": "prefix",
        "keep": "still-visible",
    }

    out = tool._redact_stage(stage)

    assert out["system"] == tool.REDACTION_MASK
    assert out["system_prefix"] == tool.REDACTION_MASK
    assert out["keep"] == "still-visible"
    assert out["stage"] == "provider"


def test_load_event_fixtures_parses_journey_and_invalid_rejected(tmp_path: Path) -> None:
    good = tmp_path / "good.jsonl"
    good.write_text(
        json.dumps({
            "journey": "command",
            "name": "c1",
            "event": {"post_type": "message", "message_type": "group"},
        }),
        encoding="utf-8",
    )
    fixtures = tool.load_event_fixtures(good)

    assert len(fixtures) == 1
    assert fixtures[0].journey == "command"
    assert fixtures[0].name == "c1"

    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({"journey": "wat", "event": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown journey"):
        tool.load_event_fixtures(bad)


def test_default_fixture_journey_is_llm(tmp_path: Path) -> None:
    path = tmp_path / "f.jsonl"
    path.write_text(json.dumps({"name": "bare", "event": {}}), encoding="utf-8")

    fixtures = tool.load_event_fixtures(path)

    assert fixtures[0].journey == "llm"


def test_repair_hint_maps_status_to_actionable_guide() -> None:
    delivered = tool.EventResult(
        "A",
        "c",
        "delivered",
        journey="command",
        assertions={"passed": True},
    )
    gated = tool.EventResult("A", "c", "gate_skipped", journey="matcher")
    failed = tool.EventResult(
        "A",
        "c",
        "failed",
        journey="command",
        error="TimeoutError: boom",
        error_class="TimeoutError",
    )

    assert "assertions passed" in (tool._repair_hint(delivered) or "")
    assert "Expected rejection" in (tool._repair_hint(gated) or "")
    assert "TimeoutError" in (tool._repair_hint(failed) or "")


def test_build_parser_exposes_journey_and_out(tmp_path: Path) -> None:
    parser = tool.build_parser()
    args = parser.parse_args([
        "--fixtures",
        str(tmp_path / "f.jsonl"),
        "--journey",
        "command",
        "--out",
        str(tmp_path / "out.jsonl"),
    ])

    assert args.journey == "command"
    assert args.out == tmp_path / "out.jsonl"


def test_run_event_case_command_journey_captures_route_and_outbound(monkeypatch) -> None:
    import asyncio
    from types import SimpleNamespace

    import nonebot
    from nonebot.adapters.onebot.v11 import Adapter

    from tools.llm_event_harness import (
        EventFixture,
        build_group_message_payload,
        run_event_case,
    )

    payload = build_group_message_payload(
        text="#pallas",
        images=[],
        to_me=False,
        bot_id="10001",
        group_id=20002,
        user_id=30003,
        message_id=40004,
        sender_nickname="<redacted>",
        sender_role="member",
    )

    async def dispatch(bot, event) -> None:
        await bot.call_api("send_group_msg", group_id=event.group_id, message="status ok")

    runtime = SimpleNamespace(adapter=Adapter(nonebot.get_driver()), dispatch=dispatch)

    result = asyncio.run(
        run_event_case(
            EventFixture("command.success", payload, journey="command"),
            prompt="",
            provider="test-provider",
            model="test-model",
            temperature=0.7,
            timeout=5.0,
            variant="A",
            runtime=runtime,
        )
    )

    assert result.status == "delivered"
    assert result.journey == "command"
    assert result.outbound_actions
    row = result.as_dict(redact=True)
    assert row["route"] == "direct"
    assert row["outbound_actions"][0]["params"]["message"] == tool.REDACTION_MASK


def test_evaluate_expect_reports_passing_and_failing_checks() -> None:
    fixture = tool.EventFixture(
        name="command.success",
        event={},
        journey="command",
        expect={"route": "direct", "status": "delivered", "outbound": 1},
    )
    passing = tool.EventResult(
        "A",
        "command.success",
        "delivered",
        journey="command",
        route="direct",
        outbound_actions=[{"action": "send_group_msg", "params": {"message": "x"}}],
    )
    failing = tool.EventResult(
        "A",
        "command.success",
        "timeout",
        journey="command",
        route="direct",
        outbound_actions=[],
    )

    ok = tool.evaluate_expect(fixture, passing)
    bad = tool.evaluate_expect(fixture, failing)

    assert ok["passed"] is True
    assert ok["checks"] == {"route": True, "status": True, "outbound": True}
    assert bad["passed"] is False
    assert bad["checks"]["status"] is False


def test_evaluate_expect_without_expect_is_neutral() -> None:
    fixture = tool.EventFixture(name="c", event={}, journey="llm", expect=None)
    result = tool.EventResult("A", "c", "timeout")

    assert tool.evaluate_expect(fixture, result) == {"expected": {}, "checks": {}, "passed": False}


def test_load_event_fixtures_parses_expect(tmp_path: Path) -> None:
    path = tmp_path / "f.jsonl"
    path.write_text(
        json.dumps({
            "journey": "matcher",
            "name": "m1",
            "event": {"post_type": "message"},
            "expect": {"route": "matcher", "status": "delivered", "outbound": 1},
        }),
        encoding="utf-8",
    )

    fixtures = tool.load_event_fixtures(path)

    assert fixtures[0].expect == {"route": "matcher", "status": "delivered", "outbound": 1}
