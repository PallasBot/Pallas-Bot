from __future__ import annotations

import packages.repeater.activity_gate as activity_gate


def test_blocks_proactive_speak_for_banned_group(monkeypatch) -> None:
    monkeypatch.setattr(activity_gate, "is_group_banned_fast", lambda _gid: True)
    monkeypatch.setattr(activity_gate, "group_has_hosted_activity", lambda _gid: False)
    assert activity_gate.blocks_proactive_speak(12345) is True


def test_allows_proactive_speak_when_not_banned_and_idle(monkeypatch) -> None:
    monkeypatch.setattr(activity_gate, "is_group_banned_fast", lambda _gid: False)
    monkeypatch.setattr(activity_gate, "group_has_hosted_activity", lambda _gid: False)
    assert activity_gate.blocks_proactive_speak(12345) is False


def test_group_is_banned_fail_open_when_snapshot_not_ready(monkeypatch) -> None:
    monkeypatch.setattr(activity_gate, "is_group_banned_fast", lambda _gid: None)
    assert activity_gate.group_is_banned(12345) is False


def test_hosted_activity_still_blocks(monkeypatch) -> None:
    monkeypatch.setattr(activity_gate, "is_group_banned_fast", lambda _gid: False)
    monkeypatch.setattr(activity_gate, "group_has_hosted_activity", lambda _gid: True)
    assert activity_gate.blocks_proactive_speak(12345) is True
