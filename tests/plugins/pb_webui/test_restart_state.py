from __future__ import annotations

import packages.pb_webui.restart_state as rs


def test_restart_runtime_fields_default() -> None:
    rs.clear_restart_requested()
    fields = rs.restart_runtime_fields()
    assert fields["restarting"] is False
    assert "ok" not in fields
    assert isinstance(fields["boot_id"], str)
    assert fields["boot_id"]


def test_mark_restart_requested_sets_restarting_and_ok_false() -> None:
    rs.clear_restart_requested()
    boot_before = rs.get_boot_id()
    rs.mark_restart_requested(workers_only=False)
    fields = rs.restart_runtime_fields()
    assert fields["restarting"] is True
    assert fields["ok"] is False
    assert fields["boot_id"] == boot_before
    assert "restart_workers_only" not in fields


def test_mark_restart_workers_only_flag() -> None:
    rs.clear_restart_requested()
    rs.mark_restart_requested(workers_only=True)
    fields = rs.restart_runtime_fields()
    assert fields["restarting"] is True
    assert fields["restart_workers_only"] is True


def test_clear_restart_requested() -> None:
    rs.mark_restart_requested()
    rs.clear_restart_requested()
    fields = rs.restart_runtime_fields()
    assert fields["restarting"] is False
