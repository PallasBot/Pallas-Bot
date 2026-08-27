from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from tools import llm_persona_ab as tool


def test_build_parser_default_mode_is_direct(tmp_path) -> None:
    parser = tool.build_parser()
    args = parser.parse_args(["--out", str(tmp_path / "out.jsonl")])

    assert args.mode == "direct"
    assert args.sender_role == "member"
    assert args.bot_id == "10001"
    assert args.group_id == "20002"
    assert args.user_id == "30003"
    assert args.to_me is False
    assert args.image is None
    assert args.text == ""
    assert args.fixture is None


def test_build_parser_event_fields(tmp_path) -> None:
    parser = tool.build_parser()
    args = parser.parse_args([
        "--mode",
        "event",
        "--to-me",
        "--image",
        "http://example.com/a.png",
        "--image",
        "local/b.png",
        "--sender-role",
        "owner",
        "--bot-id",
        "111",
        "--group-id",
        "222",
        "--user-id",
        "333",
        "--sender-nickname",
        "昵称",
        "--fixture",
        str(tmp_path / "fixture.jsonl"),
        "--out",
        str(tmp_path / "out.jsonl"),
    ])

    assert args.mode == "event"
    assert args.to_me is True
    assert args.image == ["http://example.com/a.png", "local/b.png"]
    assert args.sender_role == "owner"
    assert args.bot_id == "111"
    assert args.group_id == "222"
    assert args.user_id == "333"
    assert args.sender_nickname == "昵称"
    assert args.fixture == tmp_path / "fixture.jsonl"


class _FakeResult:
    def __init__(self, status: str, reply: str, route: str = "") -> None:
        self.status = status
        self.reply = reply
        self.route = route
        self.request_id = "req-1"
        self.api_calls = [{"action": "send_group_msg"}]
        self.stages = [{"stage": "provider", "status": "prompted"}]
        self.error = None
        self.prompt_hits = ["prompt-A"]

    def as_dict(self) -> dict:
        return {
            "variant": "A",
            "case": "cli",
            "status": self.status,
            "route": self.route,
            "request_id": self.request_id,
            "reply": self.reply,
            "api_calls": self.api_calls,
            "stages": self.stages,
            "error": self.error,
            "prompt_hits": self.prompt_hits,
        }


async def _run(main_argv: list[str]) -> int:
    return await tool.main(main_argv)


def test_event_mode_writes_two_variant_rows(tmp_path, monkeypatch) -> None:
    base_a = tmp_path / "base_a.txt"
    base_b = tmp_path / "base_b.txt"
    base_a.write_text("prompt-a", encoding="utf-8")
    base_b.write_text("prompt-b", encoding="utf-8")
    out = tmp_path / "out.jsonl"

    captured_calls: list[dict] = []

    async def fake_run_event_case(fixture, **kwargs):
        captured_calls.append({"name": fixture.name, **kwargs})
        reply = "reply:" + (kwargs.get("prompt") or "")[:20]
        return _FakeResult(status="delivered", reply=reply, route="llm_chat")

    monkeypatch.setattr("tools.llm_event_harness.run_event_case", fake_run_event_case)

    code = asyncio.run(
        _run([
            "--mode",
            "event",
            "--text",
            "你好",
            "--to-me",
            "--base-a",
            str(base_a),
            "--base-b",
            str(base_b),
            "--out",
            str(out),
        ])
    )

    assert code == 0
    assert len(captured_calls) == 2
    assert captured_calls[0]["variant"] == "A"
    assert captured_calls[0]["prompt"] == "prompt-a"
    assert captured_calls[1]["variant"] == "B"
    assert captured_calls[1]["prompt"] == "prompt-b"

    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["variant"] == "A"
    assert rows[0]["status"] == "delivered"
    assert rows[0]["case"] == "cli"
    assert rows[0]["reply"] == "reply:prompt-a"
    assert rows[0]["prompt_hits"] == ["prompt-A"]
    assert rows[1]["variant"] == "B"


def test_direct_mode_keeps_original_rows(tmp_path, monkeypatch) -> None:
    base_a = tmp_path / "base_a.txt"
    base_a.write_text("prompt-a", encoding="utf-8")
    out = tmp_path / "out.jsonl"

    async def fake_complete(messages, temperature):
        return "direct-reply"

    async def fake_run_case(complete, base, case, **kwargs):
        return "direct-reply"

    monkeypatch.setattr(tool, "resolve_completion", lambda p, m: fake_complete)
    monkeypatch.setattr(tool, "run_case", fake_run_case)

    code = asyncio.run(
        _run([
            "--mode",
            "direct",
            "--case",
            "早安吐槽",
            "--base-a",
            str(base_a),
            "--out",
            str(out),
        ])
    )

    assert code == 0
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert rows == [{"variant": "A", "case": "早安吐槽", "user": "早", "reply": "direct-reply"}]


def test_event_mode_from_fixture(tmp_path, monkeypatch) -> None:
    base_a = tmp_path / "base_a.txt"
    base_a.write_text("prompt-a", encoding="utf-8")
    fixture = tmp_path / "fixture.jsonl"
    fixture.write_text(
        json.dumps({"name": "custom", "event": {"post_type": "message", "message_type": "group"}}) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.jsonl"

    captured: list[dict] = []

    async def fake_run_event_case(fixture_obj, **kwargs):
        captured.append({"name": fixture_obj.name, **kwargs})
        return _FakeResult(status="gate_skipped", reply="")

    monkeypatch.setattr("tools.llm_event_harness.run_event_case", fake_run_event_case)
    monkeypatch.setattr("tools.llm_event_harness.load_event_fixtures", lambda p: [SimpleNamespace(name="custom")])

    code = asyncio.run(
        _run([
            "--mode",
            "event",
            "--fixture",
            str(fixture),
            "--base-a",
            str(base_a),
            "--out",
            str(out),
        ])
    )

    assert code == 0
    assert captured[0]["name"] == "custom"
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["case"] == "custom"
    assert rows[0]["status"] == "gate_skipped"
